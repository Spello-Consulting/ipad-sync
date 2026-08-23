"""Tests for the startup checks."""

import pytest
from fakes import FakeDevice, FakePlaylist

from ipad_sync.models import AppInfo, DiskUsage
from ipad_sync.startup import StartupChecker, StartupError
from ipad_sync.usb_speed import UsbLinkSpeed


def _make_checker(
    tmp_path,
    *,
    device=None,
    playlist=None,
    app_name="Infuse",
    bundle_id=None,
    simulate=False,
    log=None,
    usb_speed_probe=lambda _serial: None,
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
        log=log,
        usb_speed_probe=usb_speed_probe,
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
        usb_speed_probe=lambda _s: None,
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


# -- free-space check ------------------------------------------------------------


def test_free_space_reported_with_purgeable_note(tmp_path):
    """The free-space check logs the figure and populates the result."""
    messages: list[tuple[str, str]] = []
    device = FakeDevice(
        apps=[AppInfo("com.firecore.infuse", "Infuse")],
        disk_usage=DiskUsage(total_capacity=256_000_000_000, available=9_529_348_096),
    )
    checker = _make_checker(
        tmp_path, device=device, log=lambda msg, level: messages.append((msg, level))
    )

    result = checker.run()

    assert result.free_space_bytes == 9_529_348_096
    assert result.total_capacity_bytes == 256_000_000_000
    assert any(
        "iPad storage:" in m and "free of" in m and "purgeable" in m
        for m, _level in messages
    )


def test_free_space_unavailable_does_not_abort(tmp_path):
    """A disk-usage probe failure is informational, never fatal."""
    device = FakeDevice(
        apps=[AppInfo("com.firecore.infuse", "Infuse")],
        disk_usage_error="lockdown said no",
    )
    checker = _make_checker(tmp_path, device=device)

    result = checker.run()

    assert result.free_space_bytes is None
    assert result.total_capacity_bytes is None
    assert result.bundle_id == "com.firecore.infuse"


def test_free_space_skipped_in_simulation(tmp_path):
    """Simulation mode reports no free space (no device to probe)."""
    checker = StartupChecker(
        app_name="Infuse",
        media_folder=tmp_path,
        configured_bundle_id="com.firecore.infuse",
        device=None,
        playlist=FakePlaylist(exists=True),
        simulate=True,
    )

    result = checker.run()

    assert result.free_space_bytes is None


# -- USB link-speed check --------------------------------------------------------


def test_usb_speed_warns_when_slow(tmp_path):
    """A USB 2.0 link produces a warning message."""
    messages: list[tuple[str, str]] = []
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(
        tmp_path,
        device=device,
        log=lambda msg, level: messages.append((msg, level)),
        usb_speed_probe=lambda _s: UsbLinkSpeed(2, "High Speed (USB 2.0)", 480.0),
    )
    checker.run()

    warnings = [m for m, level in messages if level == "warning"]
    assert any(
        "USB link is slow" in m and "480 Mbps" in m and "60 MB/s" in m for m in warnings
    )


def test_usb_speed_reports_when_fast(tmp_path):
    """A USB 3 link is reported at summary level with no warning."""
    messages: list[tuple[str, str]] = []
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(
        tmp_path,
        device=device,
        log=lambda msg, level: messages.append((msg, level)),
        usb_speed_probe=lambda _s: UsbLinkSpeed(
            4, "SuperSpeed+ (USB 3.1 Gen 2)", 10000.0
        ),
    )
    checker.run()

    assert any(
        "USB link speed" in m and "10 Gbps" in m and level == "summary"
        for m, level in messages
    )
    assert not any(level == "warning" for _m, level in messages)


def test_usb_speed_unknown_is_skipped(tmp_path):
    """An undeterminable speed does not abort or warn."""
    device = FakeDevice(apps=[AppInfo("com.firecore.infuse", "Infuse")])
    checker = _make_checker(tmp_path, device=device, usb_speed_probe=lambda _s: None)
    # Should not raise.
    assert checker.run().bundle_id == "com.firecore.infuse"
