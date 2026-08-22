"""Ensure the test doubles and real services satisfy the boundary protocols.

These guard against a fake drifting out of sync with the real interface (as would
happen if the real service gained a method the startup checks call).
"""

from fakes import FakeDevice, FakePlaylist

from ipad_sync.appletv import PlaylistService
from ipad_sync.device import IPadDevice
from ipad_sync.protocols import DeviceProbe, PlaylistProbe


def test_fake_playlist_conforms():
    """The playlist fake exposes the probe interface."""
    assert isinstance(FakePlaylist(), PlaylistProbe)


def test_fake_device_conforms():
    """The device fake exposes the probe interface."""
    assert isinstance(FakeDevice(), DeviceProbe)


def test_real_playlist_conforms(tmp_path):
    """The real playlist service exposes the probe interface."""
    service = PlaylistService("iPad Sync", tmp_path, tmp_path)
    assert isinstance(service, PlaylistProbe)


def test_real_device_conforms():
    """The real device facade exposes the probe interface."""
    device = IPadDevice()
    try:
        assert isinstance(device, DeviceProbe)
    finally:
        device.close()


def test_probe_requires_get_name():
    """A probe missing get_name is rejected (regression guard)."""

    class Incomplete:
        def exists(self) -> bool:  # noqa: PLR6301 - shape-only stub for the check
            return False

    assert not isinstance(Incomplete(), PlaylistProbe)
