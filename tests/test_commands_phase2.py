"""Tests for the Phase 2 commands (list-playlist, list-ipad, compare)."""

from fakes import FakePlaylist

from ipad_sync.commands import cmd_compare, cmd_list_ipad, cmd_list_playlist
from ipad_sync.models import MediaItem
from ipad_sync.storage import SimulationStorageManager


def _collect_log():
    """Build a log callable that records its messages.

    Returns:
        A ``(log_callable, messages_list)`` pair.
    """
    messages: list[str] = []
    return (lambda msg, _level: messages.append(msg)), messages


def test_cmd_list_playlist_returns_items_and_logs():
    """list-playlist returns the read items and logs a rendered table."""
    items = [MediaItem(rel_path="a.m4v", size=10, name="A")]
    log, messages = _collect_log()

    result = cmd_list_playlist(FakePlaylist(items=items), log)

    assert result == items
    assert any("a.m4v" in m for m in messages)


def test_cmd_list_ipad_lists_simulation_storage(tmp_path):
    """list-ipad lists files from a connected storage manager."""
    src = tmp_path / "src.m4v"
    src.write_bytes(b"12345")
    log, messages = _collect_log()

    with SimulationStorageManager(tmp_path / "docs") as storage:
        storage.push_file(src, "Show/ep.m4v")
        result = cmd_list_ipad(storage, log)

    assert [i.rel_path for i in result] == ["Show/ep.m4v"]
    assert any("Show/ep.m4v" in m for m in messages)


def test_cmd_compare_combines_playlist_and_ipad(tmp_path):
    """Compare reads both sides and returns a CompareResult."""
    src = tmp_path / "src.m4v"
    src.write_bytes(b"12345")
    playlist_items = [
        MediaItem(rel_path="keep.m4v", size=5, name="keep", abs_path="/m/keep.m4v"),
        MediaItem(rel_path="new.m4v", size=5, name="new", abs_path="/m/new.m4v"),
    ]
    log, _messages = _collect_log()

    with SimulationStorageManager(tmp_path / "docs") as storage:
        storage.push_file(src, "keep.m4v")
        storage.push_file(src, "stale.m4v")
        result = cmd_compare(FakePlaylist(items=playlist_items), storage, log)

    assert [i.rel_path for i in result.to_copy] == ["new.m4v"]
    assert [i.rel_path for i in result.to_delete] == ["stale.m4v"]
    assert [i.rel_path for i in result.in_sync] == ["keep.m4v"]
