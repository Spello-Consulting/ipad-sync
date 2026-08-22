"""Tests for the to-playlist command."""

import pytest

from ipad_sync import commands
from ipad_sync.commands import cmd_to_playlist
from ipad_sync.models import MediaItem
from ipad_sync.storage import SimulationStorageManager


class FakeWritablePlaylist:
    """A playlist stand-in recording add/remove calls."""

    def __init__(self, items=None):
        self._items = items or []
        self.added: list[str] = []
        self.removed: list[str] = []

    def read(self):
        return list(self._items)

    def add_tracks(self, posix_paths):
        self.added.extend(posix_paths)
        return len(posix_paths)

    def remove_tracks(self, posix_paths):
        self.removed.extend(posix_paths)
        return len(posix_paths)


@pytest.fixture
def media(tmp_path):
    """A media folder factory.

    Returns:
        A ``(root, make)`` pair; ``make(rel)`` creates a media file under root.
    """
    root = tmp_path / "media"
    root.mkdir()

    def make(rel: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    return root, make


def _ipad_with(tmp_path, *rels):
    """Build a connected simulation storage populated with the given files.

    Returns:
        A connected :class:`SimulationStorageManager`.
    """
    src = tmp_path / "src.m4v"
    src.write_bytes(b"x")
    storage = SimulationStorageManager(tmp_path / "docs")
    storage.connect()
    for rel in rels:
        storage.push_file(src, rel)
    return storage


def test_to_playlist_adds_and_removes(tmp_path, media):
    """IPad files present locally are added; playlist tracks not on iPad are removed."""
    root, make = media
    make("new.m4v")
    storage = _ipad_with(tmp_path, "new.m4v", "keep.m4v")
    make("keep.m4v")
    playlist = FakeWritablePlaylist(
        items=[
            MediaItem("keep.m4v", 10, abs_path=str(root / "keep.m4v"), missing=False),
            MediaItem("old.m4v", 10, abs_path="/Volumes/Data/old.m4v", missing=False),
        ]
    )

    ok = cmd_to_playlist(playlist, storage, root, lambda *_: None, assume_yes=True)
    storage.close()

    assert ok is True
    assert playlist.added == [str(root / "new.m4v")]
    assert playlist.removed == ["/Volumes/Data/old.m4v"]


def test_to_playlist_skips_missing_from_media(tmp_path, media):
    """An iPad file with no local media is not added."""
    root, _make = media
    storage = _ipad_with(tmp_path, "gone.m4v")
    playlist = FakeWritablePlaylist(items=[])

    ok = cmd_to_playlist(playlist, storage, root, lambda *_: None, assume_yes=True)
    storage.close()

    assert ok is True
    assert playlist.added == []


def test_to_playlist_nothing_to_do(tmp_path, media):
    """When already mirrored, no add/remove calls are made."""
    root, make = media
    make("keep.m4v")
    storage = _ipad_with(tmp_path, "keep.m4v")
    playlist = FakeWritablePlaylist(
        items=[
            MediaItem("keep.m4v", 10, abs_path=str(root / "keep.m4v"), missing=False)
        ]
    )

    ok = cmd_to_playlist(playlist, storage, root, lambda *_: None, assume_yes=True)
    storage.close()

    assert ok is True
    assert playlist.added == []
    assert playlist.removed == []


def test_to_playlist_user_declines(tmp_path, media, monkeypatch):
    """Declining the confirmation makes no changes."""
    root, make = media
    make("new.m4v")
    storage = _ipad_with(tmp_path, "new.m4v")
    playlist = FakeWritablePlaylist(items=[])
    monkeypatch.setattr(commands, "confirm", lambda *_a, **_k: False)

    ok = cmd_to_playlist(playlist, storage, root, lambda *_: None)
    storage.close()

    assert ok is False
    assert playlist.added == []


def test_to_playlist_interrupt_before_apply(tmp_path, media):
    """An interrupt before applying makes no changes."""
    root, make = media
    make("new.m4v")
    storage = _ipad_with(tmp_path, "new.m4v")
    playlist = FakeWritablePlaylist(items=[])

    ok = cmd_to_playlist(
        playlist,
        storage,
        root,
        lambda *_: None,
        assume_yes=True,
        should_abort=lambda: True,
    )
    storage.close()

    assert ok is False
    assert playlist.added == []
    assert playlist.removed == []
