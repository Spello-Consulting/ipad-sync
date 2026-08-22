"""Tests for the command layer."""

from ipad_sync.commands import cmd_ipad_apps
from ipad_sync.models import AppInfo
from ipad_sync.startup import StartupResult


def test_cmd_ipad_apps_returns_and_logs(tmp_path):
    """ipad-apps returns the app list and logs a rendered table."""
    apps = [AppInfo("com.firecore.infuse", "Infuse")]
    startup = StartupResult(media_folder=tmp_path, simulate=False, apps=apps)

    logged: list[tuple[str, str]] = []

    result = cmd_ipad_apps(startup, lambda msg, level: logged.append((msg, level)))

    assert result == apps
    assert len(logged) == 1
    message, level = logged[0]
    assert "com.firecore.infuse" in message
    assert level == "summary"
