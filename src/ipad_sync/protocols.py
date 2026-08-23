"""Structural interfaces for the device and playlist boundaries.

The startup checker depends only on these narrow protocols, so both the real
services and the test doubles satisfy them structurally. They are
``runtime_checkable`` so a test can assert a fake still conforms (catching a
missing method before it fails deep inside a run).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ipad_sync.models import AppInfo, DiskUsage


@runtime_checkable
class PlaylistProbe(Protocol):
    """The playlist operations used by the startup checks."""

    def exists(self) -> bool:
        """Return whether the playlist exists."""
        ...

    def get_name(self) -> str:
        """Return the playlist's name."""
        ...


@runtime_checkable
class DeviceProbe(Protocol):
    """The device operations used by the startup checks."""

    def list_usb_serials(self) -> list[str]:
        """Return the serials of USB-connected devices."""
        ...

    def connect(self, pair_timeout: float | None = None) -> None:
        """Open a lockdown connection, pairing if needed."""
        ...

    def list_apps(self, application_type: str = "User") -> list[AppInfo]:
        """List installed applications."""
        ...

    def disk_usage(self) -> DiskUsage:
        """Return the iPad's device-wide storage figures."""
        ...
