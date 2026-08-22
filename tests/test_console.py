"""Tests for ipad_sync.console."""

import builtins

import pytest

from ipad_sync.compare import compare
from ipad_sync.console import (
    confirm,
    format_duration,
    format_progress,
    format_size,
    render_app_list,
    render_compare,
    render_media_list,
    render_playlist_update,
)
from ipad_sync.models import AppInfo, MediaItem, PlaylistUpdate


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


# -- media list / compare rendering ----------------------------------------------


def test_render_media_list_empty_uses_message():
    """An empty list shows the title and the empty message."""
    rendered = render_media_list([], "iPad Documents:", "  (no files on iPad)")
    assert "iPad Documents:" in rendered
    assert "(no files on iPad)" in rendered


def test_render_media_list_shows_files_and_total():
    """Each file and a total appear; missing files are marked."""
    items = [
        MediaItem(rel_path="a.m4v", size=1024),
        MediaItem(rel_path="b.m4v", size=0, missing=True),
    ]
    rendered = render_media_list(items, "Playlist:", "(empty)")
    assert "a.m4v" in rendered
    assert "1.0 KB" in rendered
    assert "MISSING" in rendered
    assert "2 file(s)" in rendered


def test_render_compare_summarises_actions():
    """The compare summary lists copies, deletions and missing sources."""
    playlist = [
        MediaItem(rel_path="new.m4v", size=2048, name="new"),
        MediaItem(rel_path="gone.m4v", size=0, name="Gone Pilot", missing=True),
    ]
    ipad = [MediaItem(rel_path="old.m4v", size=100)]
    rendered = render_compare(compare(playlist, ipad))

    assert "To copy to iPad:   1 file(s)" in rendered
    assert "To delete on iPad: 1 file(s)" in rendered
    assert "+ new.m4v" in rendered
    assert "- old.m4v" in rendered
    assert "! Gone Pilot" in rendered  # missing tracks shown by name, not path


# -- progress formatting ---------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0:00"), (9, "0:09"), (75, "1:15"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_duration(seconds, expected):
    """Durations render as mm:ss or h:mm:ss."""
    assert format_duration(seconds) == expected


def test_format_progress_includes_percent_and_eta():
    """Progress shows percentage, totals and an ETA once underway."""
    text = format_progress(
        done_bytes=50 * 1024**2, total_bytes=100 * 1024**2, elapsed_seconds=5
    )
    assert "50%" in text
    assert "left" in text
    assert "/s" in text


def test_format_progress_no_eta_before_any_bytes():
    """With nothing transferred yet there is no ETA (avoids divide-by-zero)."""
    text = format_progress(done_bytes=0, total_bytes=1000, elapsed_seconds=0)
    assert "0%" in text
    assert "left" not in text


def test_render_playlist_update_summarises():
    """The playlist-update summary lists adds, removes and skipped files."""
    update = PlaylistUpdate(
        to_add=[MediaItem(rel_path="new.m4v", size=10, abs_path="/m/new.m4v")],
        to_remove=[MediaItem(rel_path="old.m4v", size=10)],
        in_sync=[MediaItem(rel_path="keep.m4v", size=10)],
        missing_on_mac=[MediaItem(rel_path="gone.m4v", size=10)],
    )
    rendered = render_playlist_update(update)

    assert "To add to playlist:      1 track(s)" in rendered
    assert "To remove from playlist: 1 track(s)" in rendered
    assert "+ new.m4v" in rendered
    assert "- old.m4v" in rendered
    assert "! gone.m4v" in rendered
