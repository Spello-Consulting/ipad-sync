"""Tests for the startup checks."""

import pytest
from fakes import FakeDevice, FakePlaylist

from ipad_sync.models import AppInfo
from ipad_sync.startup import StartupChecker, StartupError


def _make_checker(
    tmp_path,
    *,
    device=None,
    playlist=None,
    app_name="Infuse",
    bundle_id=None,
    simulate=False,
):
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    return StartupChecker(
        app_name=app_name,
        media_folder=media,
        configured_bundle_id=bundle_id,
        device=device if device is not None else FakeDevice(),
        playlist=playlist if playlist is not None else FakePlaylist(exists=False),
        simulate=simulate,
    )


def test_run_success_resolves_bundle_id(tmp_path):
    """A full run resolves the app name to its bundle id."""
    apps = [
        AppInfo(bundle_id="com.firecore.infuse", display_name="Infuse"),
        AppInfo(bundle_id="com.apple.mobilesafari", display_name="Safari"),
    ]
    device = FakeDevice(apps=apps)
    checker = _make_checker(tmp_path, device=device)

    result = checker.run()

    assert result.bundle_id == "com.firecore.infuse"
    assert result.apps == apps
    assert result.playlist_exists is False
    assert device.connected is True


def test_run_reports_playlist_exists(tmp_path):
    """Playlist existence is carried into the result."""
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(tmp_path, device=device, playlist=FakePlaylist(exists=True))

    assert checker.run().playlist_exists is True


def test_no_usb_device_fails(tmp_path):
    """An empty USB device list is a hard failure."""
    checker = _make_checker(tmp_path, device=FakeDevice(serials=[]))
    with pytest.raises(StartupError, match="No iPad connected"):
        checker.run()


def test_trust_failure_fails(tmp_path):
    """A pairing/connection error is a hard failure."""
    checker = _make_checker(tmp_path, device=FakeDevice(connect_error="denied"))
    with pytest.raises(StartupError, match="trust"):
        checker.run()


def test_missing_media_folder_fails(tmp_path):
    """A non-existent media folder is a hard failure."""
    checker = StartupChecker(
        app_name="Infuse",
        media_folder=tmp_path / "nope",
        configured_bundle_id=None,
        device=FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")]),
        playlist=FakePlaylist(),
        simulate=False,
    )
    with pytest.raises(StartupError, match="does not exist"):
        checker.run()


def test_app_name_not_found_fails(tmp_path):
    """A missing target app is a hard failure with guidance."""
    device = FakeDevice(apps=[AppInfo("com.apple.mobilesafari", "Safari")])
    checker = _make_checker(tmp_path, device=device, app_name="Infuse")
    with pytest.raises(StartupError, match="No installed app named"):
        checker.run()


def test_ambiguous_app_name_fails(tmp_path):
    """Two apps with the same display name require BundleID to disambiguate."""
    device = FakeDevice(
        apps=[
            AppInfo("com.one.infuse", "Infuse"),
            AppInfo("com.two.infuse", "Infuse"),
        ]
    )
    checker = _make_checker(tmp_path, device=device)
    with pytest.raises(StartupError, match="Multiple apps named"):
        checker.run()


def test_configured_bundle_id_used_when_present(tmp_path):
    """A configured bundle id is used when it is installed."""
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(tmp_path, device=device, bundle_id="com.firecore.infuse")
    assert checker.run().bundle_id == "com.firecore.infuse"


def test_configured_bundle_id_not_installed_fails(tmp_path):
    """A configured bundle id that isn't installed fails."""
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(tmp_path, device=device, bundle_id="com.missing.app")
    with pytest.raises(StartupError, match="not installed"):
        checker.run()


def test_simulate_skips_device_checks(tmp_path):
    """Simulation mode skips USB/trust/app lookup but still checks media/playlist."""
    checker = StartupChecker(
        app_name="Infuse",
        media_folder=tmp_path,  # exists
        configured_bundle_id="com.firecore.infuse",
        device=None,
        playlist=FakePlaylist(exists=True),
        simulate=True,
    )
    result = checker.run()

    assert result.simulate is True
    assert result.apps == []
    assert result.bundle_id == "com.firecore.infuse"
    assert result.playlist_exists is True
