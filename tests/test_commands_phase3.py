"""Tests for the to-ipad command."""

import pytest
from fakes import FakePlaylist

from ipad_sync import commands
from ipad_sync.commands import cmd_to_ipad
from ipad_sync.models import MediaItem
from ipad_sync.storage import SimulationStorageManager


@pytest.fixture
def media(tmp_path):
    """A media folder factory.

    Returns:
        A callable ``make(rel, size)`` that writes a source file and returns its
        playlist :class:`MediaItem`.
    """
    root = tmp_path / "media"
    root.mkdir()

    def make(rel: str, size: int) -> MediaItem:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return MediaItem(rel_path=rel, size=size, name=rel, abs_path=str(path))

    return make


class RecordingStorage(SimulationStorageManager):
    """Simulation storage that records the order of mutations."""

    def __init__(self, root, capacity_bytes=None):
        super().__init__(root, capacity_bytes=capacity_bytes)
        self.ops: list[str] = []

    def remove_file(self, rel_path):
        self.ops.append(f"del:{rel_path}")
        super().remove_file(rel_path)

    def push_file(self, local_path, rel_path, on_progress=None):
        self.ops.append(f"copy:{rel_path}")
        super().push_file(local_path, rel_path, on_progress)


def test_to_ipad_empty_playlist_aborts(tmp_path):
    """An empty playlist aborts without touching the iPad."""
    src = tmp_path / "src.m4v"
    src.write_bytes(b"x")
    with SimulationStorageManager(tmp_path / "docs") as storage:
        storage.push_file(src, "existing.m4v")
        ok = cmd_to_ipad(
            FakePlaylist(items=[]), storage, lambda *_: None, assume_yes=True
        )
        remaining = [i.rel_path for i in storage.list_files()]

    assert ok is False
    assert remaining == ["existing.m4v"]  # untouched


def test_to_ipad_mirrors_and_deletes_before_copies(tmp_path, media):
    """to-ipad deletes extras then copies new files, preserving relative paths."""
    keep = media("keep.m4v", 10)
    new = media("Star Trek/Season 2/ep.m4v", 20)
    stale_src = tmp_path / "stale.m4v"
    stale_src.write_bytes(b"z" * 5)

    with RecordingStorage(tmp_path / "docs") as storage:
        storage.push_file(stale_src, "stale.m4v")
        storage.push_file(stale_src, "keep.m4v")  # already in sync
        storage.ops.clear()  # ignore setup pushes; only record what the command does

        ok = cmd_to_ipad(
            FakePlaylist(items=[keep, new]), storage, lambda *_: None, assume_yes=True
        )
        rels = sorted(i.rel_path for i in storage.list_files())

    assert ok is True
    assert rels == ["Star Trek/Season 2/ep.m4v", "keep.m4v"]
    # All deletes happen before any copy.
    del_indexes = [i for i, op in enumerate(storage.ops) if op.startswith("del:")]
    copy_indexes = [i for i, op in enumerate(storage.ops) if op.startswith("copy:")]
    assert max(del_indexes) < min(copy_indexes)
    assert storage.ops.count("del:stale.m4v") == 1


def test_to_ipad_insufficient_space_aborts(tmp_path, media):
    """The sync aborts when it would drop below the minimum free space."""
    big = media("big.m4v", 200)
    with SimulationStorageManager(tmp_path / "docs", capacity_bytes=100) as storage:
        ok = cmd_to_ipad(
            FakePlaylist(items=[big]),
            storage,
            lambda *_: None,
            min_free_gb=0,
            assume_yes=True,
        )
        rels = [i.rel_path for i in storage.list_files()]

    assert ok is False
    assert rels == []  # nothing copied


def test_to_ipad_user_declines(tmp_path, media, monkeypatch):
    """Declining the confirmation makes no changes."""
    new = media("new.m4v", 10)
    monkeypatch.setattr(commands, "confirm", lambda *_a, **_k: False)
    with SimulationStorageManager(tmp_path / "docs") as storage:
        ok = cmd_to_ipad(FakePlaylist(items=[new]), storage, lambda *_: None)
        rels = [i.rel_path for i in storage.list_files()]

    assert ok is False
    assert rels == []


def test_to_ipad_nothing_to_do(tmp_path, media):
    """When already in sync, to-ipad reports success and changes nothing."""
    keep = media("keep.m4v", 10)
    with RecordingStorage(tmp_path / "docs") as storage:
        storage.push_file(tmp_path / "media" / "keep.m4v", "keep.m4v")
        storage.ops.clear()  # ignore setup push; only record what the command does
        ok = cmd_to_ipad(
            FakePlaylist(items=[keep]), storage, lambda *_: None, assume_yes=True
        )

    assert ok is True
    assert storage.ops == []  # no deletes or copies


def test_to_ipad_skips_missing_source(tmp_path, media):
    """A playlist file missing from disk is skipped, not copied."""
    present = media("here.m4v", 10)
    missing = MediaItem(
        rel_path="gone.m4v",
        size=0,
        name="gone",
        abs_path="/media/gone.m4v",
        missing=True,
    )
    with SimulationStorageManager(tmp_path / "docs") as storage:
        ok = cmd_to_ipad(
            FakePlaylist(items=[present, missing]),
            storage,
            lambda *_: None,
            assume_yes=True,
        )
        rels = [i.rel_path for i in storage.list_files()]

    assert ok is True
    assert rels == ["here.m4v"]  # missing source not copied


def test_to_ipad_stops_on_interrupt(tmp_path, media):
    """to-ipad stops between files when should_abort turns true, leaving a clean state."""
    a = media("a.m4v", 10)
    b = media("b.m4v", 10)
    calls = {"n": 0}

    def should_abort() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # allow the first copy, abort before the second

    with SimulationStorageManager(tmp_path / "docs") as storage:
        ok = cmd_to_ipad(
            FakePlaylist(items=[a, b]),
            storage,
            lambda *_: None,
            assume_yes=True,
            should_abort=should_abort,
        )
        rels = [i.rel_path for i in storage.list_files()]

    assert ok is False
    assert rels == ["a.m4v"]  # only the first file was copied; no partial second file
