"""Tests for the simulation storage manager."""

import pytest

from ipad_sync.storage import SimulationStorageManager


@pytest.fixture
def source_file(tmp_path):
    """A small local file to push.

    Returns:
        Path to a temporary file containing a short payload.
    """
    src = tmp_path / "src.m4v"
    src.write_bytes(b"hello world")
    return src


def test_requires_connect(tmp_path):
    """Operations before connect() are rejected."""
    manager = SimulationStorageManager(tmp_path / "docs")
    with pytest.raises(RuntimeError):
        manager.list_files()


def test_push_list_roundtrip_preserves_relative_path(tmp_path, source_file):
    """Pushed files appear in list_files with their relative path and size."""
    with SimulationStorageManager(tmp_path / "docs") as manager:
        manager.push_file(source_file, "Star Trek/Season 2/Amok Time.m4v")

        items = manager.list_files()

    assert len(items) == 1
    assert items[0].rel_path == "Star Trek/Season 2/Amok Time.m4v"
    assert items[0].size == len(b"hello world")


def test_push_progress_callback(tmp_path, source_file):
    """The progress callback reports the full size on completion."""
    seen: list[tuple[int, int]] = []
    with SimulationStorageManager(tmp_path / "docs") as manager:
        manager.push_file(
            source_file,
            "a.m4v",
            on_progress=lambda done, total: seen.append((done, total)),
        )

    assert seen == [(11, 11)]


def test_remove_prunes_empty_dirs(tmp_path, source_file):
    """Removing a file also prunes directories it leaves empty."""
    root = tmp_path / "docs"
    with SimulationStorageManager(root) as manager:
        manager.push_file(source_file, "Show/Season 1/ep.m4v")
        manager.remove_file("Show/Season 1/ep.m4v")

        assert manager.list_files() == []

    assert not (root / "Show").exists()


def test_remove_keeps_shared_dirs(tmp_path, source_file):
    """A shared parent directory is retained when a sibling remains."""
    root = tmp_path / "docs"
    with SimulationStorageManager(root) as manager:
        manager.push_file(source_file, "Show/Season 1/ep1.m4v")
        manager.push_file(source_file, "Show/Season 1/ep2.m4v")
        manager.remove_file("Show/Season 1/ep1.m4v")

        rels = [item.rel_path for item in manager.list_files()]

    assert rels == ["Show/Season 1/ep2.m4v"]
    assert (root / "Show" / "Season 1").exists()


def test_free_space_reflects_capacity_and_usage(tmp_path, source_file):
    """Free space is capacity minus bytes used."""
    with SimulationStorageManager(tmp_path / "docs", capacity_bytes=1000) as manager:
        assert manager.free_space_bytes() == 1000
        manager.push_file(source_file, "a.m4v")
        assert manager.free_space_bytes() == 1000 - 11


def test_list_files_skips_hidden_entries(tmp_path, source_file):
    """Hidden files and files under hidden dirs are excluded from listings."""
    with SimulationStorageManager(tmp_path / "docs") as manager:
        manager.push_file(source_file, "keep.m4v")
        # Simulate a hidden trash folder and a dotfile directly.
        trash = manager.root / ".Trash"
        trash.mkdir()
        (trash / "deleted.m4v").write_bytes(b"x")
        (manager.root / ".DS_Store").write_bytes(b"x")

        rels = [item.rel_path for item in manager.list_files()]

    assert rels == ["keep.m4v"]
