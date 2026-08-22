"""Application startup checks.

These run before every command (see the requirements) so that all iPad/Mac
approval dialogs are triggered up front and the environment is validated once. In
simulation mode the device-dependent checks are skipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ipad_sync.device import DeviceError
from ipad_sync.usb_speed import probe_usb_link_speed

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ipad_sync.models import AppInfo
    from ipad_sync.protocols import DeviceProbe, PlaylistProbe
    from ipad_sync.usb_speed import UsbLinkSpeed


class StartupError(Exception):
    """Raised when a mandatory startup check fails."""


@dataclass
class StartupResult:
    """Outcome of the startup checks, shared with the command layer.

    Attributes:
        media_folder: The validated Apple TV media root.
        simulate: Whether the app is running in simulation mode.
        apps: All apps found on the iPad (empty in simulation mode).
        bundle_id: Resolved bundle id of the target iPad app, if known.
        playlist_exists: Whether the sync playlist already exists.
    """

    media_folder: Path
    simulate: bool
    apps: list[AppInfo] = field(default_factory=list)
    bundle_id: str | None = None
    playlist_exists: bool = False


class StartupChecker:
    """Runs the mandatory pre-flight checks and resolves shared context."""

    def __init__(
        self,
        *,
        app_name: str,
        media_folder: Path,
        configured_bundle_id: str | None,
        device: DeviceProbe | None,
        playlist: PlaylistProbe,
        simulate: bool,
        log: Callable[[str, str], None] | None = None,
        usb_speed_probe: Callable[[str | None], UsbLinkSpeed | None] | None = None,
    ) -> None:
        """Create the checker.

        Args:
            app_name: Configured ``iPad.AppName`` (display name to resolve).
            media_folder: Configured ``AppleTV.MediaFolder``.
            configured_bundle_id: Optional ``iPad.BundleID`` override.
            device: Connected/creatable :class:`IPadDevice`, or ``None`` when
                simulating.
            playlist: Service used to probe playlist existence.
            simulate: Whether to skip device-dependent checks.
            log: Optional ``(message, verbosity)`` logging callable.
            usb_speed_probe: Callable returning the negotiated USB link speed for
                a serial (defaults to the real ``ioreg`` probe).
        """
        self._app_name = app_name
        self._media_folder = media_folder
        self._configured_bundle_id = configured_bundle_id
        self._device = device
        self._playlist = playlist
        self._simulate = simulate
        self._log = log
        self._usb_speed_probe = usb_speed_probe
        self._serial: str | None = None

    def _info(self, message: str) -> None:
        if self._log is not None:
            self._log(message, "summary")

    def _warn(self, message: str) -> None:
        if self._log is not None:
            self._log(message, "warning")

    def run(self) -> StartupResult:
        """Run all startup checks in order.

        Returns:
            A populated :class:`StartupResult`.
        """
        result = StartupResult(media_folder=self._media_folder, simulate=self._simulate)

        if self._simulate:
            self._info("Simulation mode: skipping USB, trust and app-lookup checks.")
            result.bundle_id = self._configured_bundle_id
        else:
            self._check_usb()
            self._check_trust()
            self._check_usb_speed()
            result.apps = self._load_apps()
            result.bundle_id = self._resolve_bundle_id(result.apps)

        self._check_media_folder()
        result.playlist_exists = self._check_playlist()
        self._info("Startup checks passed.")
        return result

    # -- individual checks ------------------------------------------------------

    def _require_device(self) -> DeviceProbe:
        if self._device is None:
            msg = "No device available (internal error: device not provided)."
            raise StartupError(msg)
        return self._device

    def _check_usb(self) -> None:
        """Check 1: an iPad is connected over USB.

        Raises:
            StartupError: If no USB device is found or discovery fails.
        """
        device = self._require_device()
        try:
            serials = device.list_usb_serials()
        except DeviceError as exc:
            raise StartupError(str(exc)) from exc
        if not serials:
            msg = "No iPad connected over USB. Connect the iPad and retry."
            raise StartupError(msg)
        self._serial = serials[0]
        self._info(f"iPad detected over USB (serial: {serials[0]}).")

    def _check_trust(self) -> None:
        """Check 2: a trust relationship exists (pair, prompting if needed).

        Raises:
            StartupError: If pairing/connection fails.
        """
        device = self._require_device()
        try:
            device.connect()
        except DeviceError as exc:
            msg = f"Could not establish trust with the iPad: {exc}"
            raise StartupError(msg) from exc
        self._info("Trust relationship with the iPad confirmed.")

    def _check_usb_speed(self) -> None:
        """Check 2b: report the negotiated USB link speed (informational).

        Never aborts the run — an undeterminable speed is simply skipped. Warns
        when the link is USB 2.0 or slower, which throttles transfers.
        """
        probe = self._usb_speed_probe or probe_usb_link_speed
        speed = probe(self._serial)
        if speed is None:
            self._info("USB link speed could not be determined (skipping).")
            return
        if speed.is_slow:
            self._warn(
                f"USB link is slow: {speed.summary}. Transfers will be slow — "
                "use a USB 3.1 Gen 2 / Thunderbolt cable for full speed."
            )
        else:
            self._info(f"USB link speed: {speed.summary}.")

    def _check_media_folder(self) -> None:
        """Check 3: the media folder exists and is readable.

        Raises:
            StartupError: If the folder is missing, not a directory or unreadable.
        """
        folder = self._media_folder
        if not folder.exists():
            msg = f"Media folder does not exist: {folder}"
            raise StartupError(msg)
        if not folder.is_dir():
            msg = f"Media folder is not a directory: {folder}"
            raise StartupError(msg)
        if not os.access(folder, os.R_OK):
            msg = f"Media folder is not readable: {folder}"
            raise StartupError(msg)
        self._info(f"Media folder OK: {folder}")

    def _check_playlist(self) -> bool:
        """Check 4: probe playlist existence (absence is not an error).

        Returns:
            True if the playlist already exists.
        """
        exists = self._playlist.exists()
        playlist_name = self._playlist.get_name()
        if exists:
            self._info(f"Apple TV playlist {playlist_name} found.")
        else:
            self._info(
                f"Apple TV playlist {playlist_name} does not exist yet (this is OK)."
            )
        return exists

    def _load_apps(self) -> list[AppInfo]:
        """Check 5a: load the installed-app list.

        Returns:
            The apps installed on the iPad.

        Raises:
            StartupError: If the app listing cannot be retrieved.
        """
        device = self._require_device()
        try:
            apps = device.list_apps()
        except DeviceError as exc:
            raise StartupError(str(exc)) from exc
        self._info(f"Retrieved {len(apps)} installed app(s) from the iPad.")
        return apps

    def _resolve_bundle_id(self, apps: list[AppInfo]) -> str:
        """Check 5b: resolve the target app's bundle id.

        Uses the configured ``iPad.BundleID`` when provided (verifying it is
        installed), otherwise matches the configured ``iPad.AppName`` against
        each app's display name.

        Args:
            apps: The installed apps to search.

        Returns:
            The resolved bundle id.

        Raises:
            StartupError: If the target app cannot be uniquely resolved.
        """
        if self._configured_bundle_id:
            for app in apps:
                if app.bundle_id == self._configured_bundle_id:
                    self._info(f"Using configured bundle id: {app.bundle_id}")
                    return app.bundle_id
            msg = f"Configured iPad.BundleID '{self._configured_bundle_id}' is not installed on the iPad."
            raise StartupError(msg)

        wanted = self._app_name.casefold()
        matches = [app for app in apps if app.display_name.casefold() == wanted]
        if not matches:
            msg = (
                f"No installed app named '{self._app_name}' found. "
                "Set iPad.BundleID in the config, or run 'ipad-apps' to see available apps."
            )
            raise StartupError(msg)
        if len(matches) > 1:
            ids = ", ".join(app.bundle_id for app in matches)
            msg = f"Multiple apps named '{self._app_name}' found ({ids}). Set iPad.BundleID to disambiguate."
            raise StartupError(msg)
        self._info(f"Resolved '{self._app_name}' to bundle id: {matches[0].bundle_id}")
        return matches[0].bundle_id
