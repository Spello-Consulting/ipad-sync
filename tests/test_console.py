"""Tests for ipad_sync.console."""

import builtins

import pytest

from ipad_sync.console import confirm, format_size, render_app_list
from ipad_sync.models import AppInfo


@pytest.mark.parametrize(
    ("num_bytes", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (5 * 1024**3, "5.0 GB"),
    ],
)
def test_format_size(num_bytes, expected):
    """Byte counts render with a sensible unit."""
    assert format_size(num_bytes) == expected


def test_render_app_list_empty():
    """An empty app list renders a friendly notice."""
    assert render_app_list([]) == "No applications found."


def test_render_app_list_aligns_and_counts():
    """The table includes each app and a total count."""
    apps = [
        AppInfo(bundle_id="com.firecore.infuse", display_name="Infuse"),
        AppInfo(bundle_id="com.apple.mobilesafari", display_name="Safari"),
    ]
    rendered = render_app_list(apps)

    assert "Infuse" in rendered
    assert "com.firecore.infuse" in rendered
    assert "Safari" in rendered
    assert "2 app(s)." in rendered


def test_confirm_assume_yes_skips_prompt(monkeypatch):
    """assume_yes returns True without touching stdin."""

    def _fail(_prompt):  # pragma: no cover - must not be called
        msg = "input should not be called"
        raise AssertionError(msg)

    monkeypatch.setattr(builtins, "input", _fail)
    assert confirm("Proceed?", assume_yes=True) is True


def test_confirm_non_tty_returns_false(monkeypatch):
    """A non-interactive stdin defaults to no."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert confirm("Proceed?") is False


@pytest.mark.parametrize(
    ("answer", "expected"), [("y", True), ("yes", True), ("n", False), ("", False)]
)
def test_confirm_interactive(monkeypatch, answer, expected):
    """Interactive answers are interpreted case-insensitively."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda _prompt: answer)
    assert confirm("Proceed?") is expected
