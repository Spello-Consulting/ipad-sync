"""Test doubles for the device and playlist boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ipad_sync.device import DeviceError
from ipad_sync.models import DiskUsage

if TYPE_CHECKING:
    from ipad_sync.models import AppInfo, MediaItem


class FakeDevice:
    """A stand-in for :class:`ipad_sync.device.IPadDevice`.

    Records calls and returns canned values so startup and command logic can be
    tested without an iPad.
    """

    def __init__(
        self,
        *,
        serials: list[str] | None = None,
        apps: list[AppInfo] | None = None,
        connect_error: str | None = None,
        list_apps_error: str | None = None,
        disk_usage: DiskUsage | None = None,
        disk_usage_error: str | None = None,
    ) -> None:
        self._serials = serials if serials is not None else ["FAKESERIAL123"]
        self._apps = apps if apps is not None else []
        self._connect_error = connect_error
        self._list_apps_error = list_apps_error
        self._disk_usage = (
            disk_usage
            if disk_usage is not None
            # ~8.8 GiB free of a 256 GB device, mirroring the real iPad.
            else DiskUsage(total_capacity=256_000_000_000, available=9_529_348_096)
        )
        self._disk_usage_error = disk_usage_error
        self.connected = False
        self.closed = False

    def list_usb_serials(self) -> list[str]:
        return self._serials

    def connect(self, pair_timeout: float | None = None) -> None:  # noqa: ARG002
        if self._connect_error is not None:
            raise DeviceError(self._connect_error)
        self.connected = True

    def list_apps(self, application_type: str = "User") -> list[AppInfo]:  # noqa: ARG002
        if self._list_apps_error is not None:
            raise DeviceError(self._list_apps_error)
        return self._apps

    def disk_usage(self) -> DiskUsage:
        if self._disk_usage_error is not None:
            raise DeviceError(self._disk_usage_error)
        return self._disk_usage

    def close(self) -> None:
        self.closed = True


class FakePlaylist:
    """A stand-in for :class:`ipad_sync.appletv.PlaylistService`."""

    def __init__(
        self,
        exists: bool = False,
        name: str = "iPad Sync",
        items: list[MediaItem] | None = None,
    ) -> None:
        self._exists = exists
        self._name = name
        self._items = items if items is not None else []

    def exists(self) -> bool:
        return self._exists

    def get_name(self) -> str:
        return self._name

    def read(self) -> list[MediaItem]:
        return list(self._items)
