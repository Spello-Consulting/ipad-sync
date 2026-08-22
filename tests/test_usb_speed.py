"""Tests for USB link-speed parsing."""

import plistlib

from ipad_sync.usb_speed import UsbLinkSpeed, parse_link_speed


def _plist(devices):
    """Serialise a list of device dicts as ioreg -a would.

    Returns:
        The XML plist bytes.
    """
    return plistlib.dumps(devices)


def test_link_speed_properties_usb2():
    """A USB 2.0 speed reports slow, 480 Mbps and 60 MB/s."""
    speed = UsbLinkSpeed(2, "High Speed (USB 2.0)", 480.0)
    assert speed.is_slow is True
    assert speed.megabytes_per_sec == 60.0
    assert speed.rate_text == "480 Mbps"
    assert "60 MB/s" in speed.summary


def test_link_speed_properties_usb3():
    """A USB 3.1 Gen 2 speed reports fast, 10 Gbps and 1250 MB/s."""
    speed = UsbLinkSpeed(4, "SuperSpeed+ (USB 3.1 Gen 2)", 10000.0)
    assert speed.is_slow is False
    assert speed.megabytes_per_sec == 1250.0
    assert speed.rate_text == "10 Gbps"


def test_parse_matches_serial_and_takes_max():
    """Entries with the same serial (dashes ignored) are matched; max speed wins."""
    devices = [
        {
            "USB Product Name": "iPad",
            "USB Serial Number": "00008103-0011",
            "Device Speed": 2,
        },
        {
            "USB Product Name": "iPad",
            "USB Serial Number": "000081030011",
            "Device Speed": 4,
        },
        {"USB Product Name": "Webcam", "USB Serial Number": "XYZ", "Device Speed": 3},
    ]
    speed = parse_link_speed(_plist(devices), "00008103-0011")
    assert speed is not None
    assert speed.device_speed == 4


def test_parse_matches_by_name_without_serial():
    """Without a serial, the iPad-named entry is used."""
    speed = parse_link_speed(
        _plist([{"USB Product Name": "iPad", "Device Speed": 2}]), None
    )
    assert speed is not None
    assert speed.device_speed == 2


def test_parse_descends_into_children():
    """The iPad is found when nested under a hub entry."""
    devices = [
        {
            "USB Product Name": "Hub",
            "Device Speed": 4,
            "IORegistryEntryChildren": [
                {
                    "USB Product Name": "iPad",
                    "USB Serial Number": "ABC",
                    "Device Speed": 2,
                }
            ],
        }
    ]
    speed = parse_link_speed(_plist(devices), "ABC")
    assert speed is not None
    assert speed.device_speed == 2


def test_parse_returns_none_when_not_found():
    """A serial that matches nothing yields None."""
    assert (
        parse_link_speed(
            _plist([{"USB Product Name": "Webcam", "Device Speed": 3}]), "NOPE"
        )
        is None
    )


def test_parse_invalid_plist_returns_none():
    """Malformed input yields None rather than raising."""
    assert parse_link_speed(b"not a plist", None) is None
