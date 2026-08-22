"""Negotiated USB link-speed detection via ``ioreg`` (macOS).

Used by the startup checks to report how fast the iPad's USB connection actually
negotiated, and to warn when it is USB 2.0 or slower (which throttles transfers).
This is informational only — failure to determine the speed never aborts a run.
"""

from __future__ import annotations

import plistlib
import subprocess  # noqa: S404 - ioreg is a trusted, fixed local binary
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from xml.parsers.expat import ExpatError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# ioreg "Device Speed" code -> (human label, nominal link speed in Mbps).
_USB_SPEEDS: dict[int, tuple[str, float]] = {
    0: ("Low Speed (USB 1.0)", 1.5),
    1: ("Full Speed (USB 1.1)", 12.0),
    2: ("High Speed (USB 2.0)", 480.0),
    3: ("SuperSpeed (USB 3.0 / 3.1 Gen 1)", 5000.0),
    4: ("SuperSpeed+ (USB 3.1 Gen 2)", 10000.0),
}

# Device Speed at or below this is considered "slow" (USB 2.0 or worse).
_SLOW_SPEED_CODE = 2

_IOREG_COMMAND = ("/usr/sbin/ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l")


@dataclass(frozen=True)
class UsbLinkSpeed:
    """The negotiated USB link speed of a connected device.

    Attributes:
        device_speed: The raw ioreg ``Device Speed`` code (0-4).
        label: A human-readable label (e.g. ``"High Speed (USB 2.0)"``).
        mbps: The nominal link speed in megabits per second.
    """

    device_speed: int
    label: str
    mbps: float

    @property
    def megabytes_per_sec(self) -> float:
        """The nominal link speed in megabytes per second (mbps / 8)."""
        return self.mbps / 8

    @property
    def is_slow(self) -> bool:
        """True when the link is USB 2.0 or slower."""
        return self.device_speed <= _SLOW_SPEED_CODE

    @property
    def rate_text(self) -> str:
        """The link speed as ``"480 Mbps"`` or ``"10 Gbps"``."""
        if self.mbps >= 1000:
            return f"{self.mbps / 1000:g} Gbps"
        return f"{self.mbps:g} Mbps"

    @property
    def summary(self) -> str:
        """A one-line description with rate in both Mb/Gbps and MB/s."""
        return (
            f"{self.label} — {self.rate_text} (~{self.megabytes_per_sec:.0f} MB/s max)"
        )


def _iter_nodes(nodes: list[Any]) -> Iterator[dict[str, Any]]:
    """Yield every device dict in an ioreg tree, descending into children."""
    for node in nodes:
        if isinstance(node, dict):
            yield node
            children = node.get("IORegistryEntryChildren")
            if isinstance(children, list):
                yield from _iter_nodes(children)


def parse_link_speed(plist_bytes: bytes, serial: str | None) -> UsbLinkSpeed | None:
    """Parse ``ioreg -a`` output for a device's negotiated link speed.

    When ``serial`` is given, only entries whose USB serial matches (ignoring
    dashes and case) are considered; otherwise entries named ``iPad`` are used.
    The highest ``Device Speed`` found is returned, since a SuperSpeed device
    enumerates on both the USB 2.0 and USB 3 buses.

    Args:
        plist_bytes: The XML plist emitted by ``ioreg -a``.
        serial: The target device serial, or ``None`` to match by name.

    Returns:
        The negotiated :class:`UsbLinkSpeed`, or ``None`` if it can't be found.
    """
    try:
        data = plistlib.loads(plist_bytes)
    except (plistlib.InvalidFileException, ExpatError, ValueError):
        return None

    target = serial.replace("-", "").casefold() if serial else None
    nodes = data if isinstance(data, list) else [data]

    best: int | None = None
    for node in _iter_nodes(nodes):
        speed = node.get("Device Speed")
        if not isinstance(speed, int):
            continue
        if target is not None:
            node_serial = (
                str(node.get("USB Serial Number", "")).replace("-", "").casefold()
            )
            if node_serial != target:
                continue
        elif "ipad" not in str(node.get("USB Product Name", "")).casefold():
            continue
        if best is None or speed > best:
            best = speed

    if best is None:
        return None
    label, mbps = _USB_SPEEDS.get(best, (f"USB device speed code {best}", 0.0))
    return UsbLinkSpeed(device_speed=best, label=label, mbps=mbps)


def probe_usb_link_speed(
    serial: str | None = None,
    log: Callable[[str, str], None] | None = None,
) -> UsbLinkSpeed | None:
    """Run ``ioreg`` and return the connected iPad's negotiated USB link speed.

    Args:
        serial: The target device serial (matched ignoring dashes/case).
        log: Optional ``(message, verbosity)`` logging callable for diagnostics.

    Returns:
        The negotiated :class:`UsbLinkSpeed`, or ``None`` if it can't be
        determined (e.g. not on macOS, ``ioreg`` missing, or device not found).
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, no shell
            list(_IOREG_COMMAND),
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if log is not None:
            log(f"Could not query USB link speed via ioreg: {exc}", "debug")
        return None
    return parse_link_speed(result.stdout, serial)
