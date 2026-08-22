"""Synchronous facade over the (async) ``pymobiledevice3`` device API.

``pymobiledevice3`` 10.x exposes every device operation as a coroutine, and an
open House Arrest (AFC) session holds a live connection that must be driven by a
single event loop for its whole lifetime. To keep the rest of the app — the CLI,
the simulation storage manager and the test suite — synchronous, all async access
is confined to this module.

An :class:`IPadDevice` owns one event loop for the duration of a CLI run. It is
created once during startup so that any iPad/Mac trust dialogs are triggered up
front, then shared by the startup checks, the ``ipad-apps`` command and the real
:class:`~ipad_sync.storage.ipad.IPadStorageManager`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self, TypeVar

from pymobiledevice3.exceptions import (
    AppNotInstalledError,
    NoDeviceConnectedError,
    PyMobileDevice3Exception,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService
from pymobiledevice3.services.installation_proxy import InstallationProxyService
from pymobiledevice3.usbmux import list_devices

from ipad_sync.models import AppInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from pymobiledevice3.lockdown import UsbmuxLockdownClient

_T = TypeVar("_T")


class DeviceError(Exception):
    """Raised when a device operation fails in a way ipad-sync should report."""


class IPadDevice:
    """Owns an event loop and lockdown session for one CLI run.

    All methods are synchronous; each drives the underlying coroutine on this
    instance's dedicated event loop. Call :meth:`connect` before any operation
    that needs the lockdown client, and :meth:`close` (ideally via a ``with``
    block) when finished.
    """

    def __init__(self, log: Callable[[str, str], None] | None = None) -> None:
        """Initialise the facade.

        Args:
            log: Optional ``(message, verbosity)`` callable (e.g. the bound
                ``SCLogger.log_message``) used for debug logging.
        """
        self._log = log
        self._loop = asyncio.new_event_loop()
        self._lockdown: UsbmuxLockdownClient | None = None
        self._afc: HouseArrestService | None = None
        self._afc_bundle_id: str | None = None

    def __enter__(self) -> Self:
        """Enter the context manager.

        Returns:
            This device instance.
        """
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close the device session on context exit."""
        self.close()

    def _debug(self, message: str) -> None:
        if self._log is not None:
            self._log(message, "debug")

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run a coroutine to completion on this instance's loop.

        Args:
            coro: The coroutine to execute.

        Returns:
            The coroutine's result.
        """
        return self._loop.run_until_complete(coro)

    # -- discovery / connection -------------------------------------------------

    def list_usb_serials(self) -> list[str]:
        """Return the serial numbers of all iOS devices connected over USB.

        Returns:
            The USB device serials, or an empty list when none are attached.
        """
        devices = self._run(list_devices())
        return [device.serial for device in devices if device.is_usb]

    def connect(self, pair_timeout: float | None = None) -> None:
        """Open a lockdown connection to the first USB device, pairing if needed.

        ``create_using_usbmux(autopair=True)`` validates an existing pairing or
        performs a new one, surfacing the iPad's Trust dialog.

        Args:
            pair_timeout: Seconds to wait for the user to accept the Trust dialog,
                or ``None`` to wait indefinitely.

        Raises:
            DeviceError: If no device is connected or the connection/pairing fails.
        """
        try:
            self._lockdown = self._run(
                create_using_usbmux(
                    autopair=True,
                    connection_type="USB",
                    pair_timeout=pair_timeout,
                )
            )
        except NoDeviceConnectedError as exc:
            msg = "No iPad connected over USB."
            raise DeviceError(msg) from exc
        except PyMobileDevice3Exception as exc:
            msg = f"Could not connect to the iPad: {exc}"
            raise DeviceError(msg) from exc

    @property
    def is_connected(self) -> bool:
        """True when :meth:`connect` has established a lockdown client."""
        return self._lockdown is not None

    def _require_lockdown(self) -> UsbmuxLockdownClient:
        if self._lockdown is None:
            msg = "Device is not connected; call connect() first."
            raise DeviceError(msg)
        return self._lockdown

    # -- installed apps ---------------------------------------------------------

    def list_apps(self, application_type: str = "User") -> list[AppInfo]:
        """List installed applications and their bundle ids.

        Args:
            application_type: ``ApplicationType`` filter; ``"User"`` (default),
                ``"System"`` or ``"Any"``.

        Returns:
            One :class:`AppInfo` per installed app, sorted by display name.

        Raises:
            DeviceError: If the app listing cannot be retrieved.
        """
        lockdown = self._require_lockdown()

        async def _lookup() -> dict[str, dict[str, Any]]:
            async with InstallationProxyService(lockdown) as proxy:
                result: dict[str, dict[str, Any]] = await proxy.get_apps(
                    application_type=application_type
                )
                return result

        try:
            raw = self._run(_lookup())
        except PyMobileDevice3Exception as exc:
            msg = f"Could not list installed apps: {exc}"
            raise DeviceError(msg) from exc

        apps = [
            AppInfo(
                bundle_id=bundle_id,
                display_name=info.get("CFBundleDisplayName", bundle_id),
            )
            for bundle_id, info in raw.items()
        ]
        apps.sort(key=lambda app: app.display_name.casefold())
        return apps

    # -- house arrest (Documents AFC) session ----------------------------------

    def open_documents(self, bundle_id: str) -> None:
        """Open an AFC session vending an app's ``Documents`` subtree.

        The session stays open (and its background reader task running) until
        :meth:`close` is called, so subsequent ``afc_*`` calls reuse it.

        Args:
            bundle_id: Bundle id of the app whose Documents to vend.

        Raises:
            DeviceError: If the app is not installed or the session cannot open.
        """
        lockdown = self._require_lockdown()

        async def _open() -> HouseArrestService:
            service = await HouseArrestService.create(
                lockdown, bundle_id, documents_only=True
            )
            await service.__aenter__()  # noqa: PLC2801 - kept open across sync calls; no public equivalent
            return service

        try:
            self._afc = self._run(_open())
            self._afc_bundle_id = bundle_id
        except AppNotInstalledError as exc:
            msg = f"App '{bundle_id}' is not installed on the iPad."
            raise DeviceError(msg) from exc
        except PyMobileDevice3Exception as exc:
            msg = f"Could not open Documents for '{bundle_id}': {exc}"
            raise DeviceError(msg) from exc

    def _require_afc(self) -> HouseArrestService:
        if self._afc is None:
            msg = "No Documents session open; call open_documents() first."
            raise DeviceError(msg)
        return self._afc

    def afc_listdir(self, path: str) -> list[str]:
        """List directory entries within the vended Documents subtree.

        Args:
            path: Directory path relative to the Documents root.

        Returns:
            The entry names in the directory.
        """
        return self._run(self._require_afc().listdir(path))

    def afc_stat(self, path: str) -> Any:
        """Return an ``os.stat``-style result for a path in Documents.

        Args:
            path: Path relative to the Documents root.

        Returns:
            The ``StatResult`` for the path.
        """
        return self._run(self._require_afc().os_stat(path))

    def afc_device_info(self) -> dict[str, str]:
        """Return the device filesystem info dict (includes free/total bytes).

        Returns:
            The AFC device-info mapping.
        """
        return self._run(self._require_afc().get_device_info())

    def afc_makedirs(self, path: str) -> None:
        """Recursively create a directory within Documents.

        Args:
            path: Directory path relative to the Documents root.
        """
        self._run(self._require_afc().makedirs(path))

    def afc_push(
        self,
        local_path: str,
        remote_path: str,
        callback: Callable[[str, str], Any] | None = None,
    ) -> None:
        """Upload a local file to a path within Documents.

        Args:
            local_path: Source file on the local machine.
            remote_path: Destination path relative to the Documents root.
            callback: Optional per-entry callback passed through to AFC.
        """
        self._run(
            self._require_afc().push(
                local_path,
                remote_path,
                callback=callback,
                progress_bar=False,
            )
        )

    def afc_rm(self, path: str) -> None:
        """Remove a file (or directory tree) within Documents.

        Args:
            path: Path relative to the Documents root.
        """
        self._run(self._require_afc().rm(path, force=True))

    # -- teardown ---------------------------------------------------------------

    def close(self) -> None:
        """Tear down the AFC session, lockdown client and event loop.

        Safe to call multiple times.
        """
        if self._loop.is_closed():
            return
        if self._afc is not None:
            try:
                self._run(self._afc.aclose())
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                self._debug(f"Error closing AFC session: {exc}")
            self._afc = None
        if self._lockdown is not None:
            try:
                self._run(self._lockdown.close())
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                self._debug(f"Error closing lockdown client: {exc}")
            self._lockdown = None
        self._loop.close()
