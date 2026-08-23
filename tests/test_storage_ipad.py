"""Tests for the device-backed storage manager's AFC path handling.

These use a fake AFC device to verify the manager anchors everything at the
``/Documents`` subtree (the vended House Arrest root) and skips hidden entries
such as Infuse's ``.Trash`` folder — the exact issues seen against a real iPad.
"""

import stat
from pathlib import Path
from types import SimpleNamespace

from ipad_sync.models import DiskUsage
from ipad_sync.storage.ipad import IPadStorageManager


class FakeAfcDevice:
    """A fake :class:`IPadDevice` exposing a canned ``/Documents`` tree."""

    def __init__(self, tree, disk_usage=None):
        self._tree = tree
        self._disk_usage = disk_usage or DiskUsage(
            total_capacity=256_000_000_000, available=2048
        )
        self.listdir_calls: list[str] = []
        self.pushed: list[tuple[str, str]] = []
        self.made_dirs: list[str] = []
        self.removed: list[str] = []

    def open_documents(self, _bundle_id):
        pass

    def disk_usage(self):
        return self._disk_usage

    def close(self):
        pass

    def afc_listdir(self, path):
        self.listdir_calls.append(path)
        return [name for name, _is_dir, _size in self._tree.get(path, [])]

    def afc_stat(self, path):
        parent, _, base = path.rpartition("/")
        for name, is_dir, size in self._tree.get(parent, []):
            if name == base:
                mode = stat.S_IFDIR if is_dir else stat.S_IFREG
                return SimpleNamespace(st_mode=mode, st_size=size)
        raise KeyError(path)

    def afc_makedirs(self, path):
        self.made_dirs.append(path)

    def afc_push(self, local, remote, callback=None):  # noqa: ARG002
        self.pushed.append((local, remote))

    def afc_rm(self, path):
        self.removed.append(path)


_TREE = {
    "/Documents": [
        ("Movie.m4v", False, 100),
        ("Star Trek", True, 0),
        (".Trash", True, 0),
    ],
    "/Documents/Star Trek": [("Season 2", True, 0)],
    "/Documents/Star Trek/Season 2": [("ep.m4v", False, 200)],
    "/Documents/.Trash": [("deleted.m4v", False, 999)],
}


def test_list_files_anchors_at_documents_and_strips_prefix():
    """Walk starts at /Documents and relative paths drop that prefix."""
    device = FakeAfcDevice(_TREE)
    manager = IPadStorageManager(device, "com.firecore.infuse")

    items = manager.list_files()

    assert device.listdir_calls[0] == "/Documents"
    assert [i.rel_path for i in items] == ["Movie.m4v", "Star Trek/Season 2/ep.m4v"]
    assert items[0].size == 100


def test_list_files_skips_hidden_trash():
    """Hidden entries like .Trash are never listed or descended into."""
    device = FakeAfcDevice(_TREE)
    manager = IPadStorageManager(device, "com.firecore.infuse")

    rels = [i.rel_path for i in manager.list_files()]

    assert not any(".Trash" in rel for rel in rels)
    assert "/Documents/.Trash" not in device.listdir_calls


def test_push_file_anchors_and_creates_parents():
    """push_file targets /Documents and makes intermediate dirs there."""
    device = FakeAfcDevice(_TREE)
    manager = IPadStorageManager(device, "com.firecore.infuse")

    manager.push_file(Path("/local/ep.m4v"), "Star Trek/Season 3/ep.m4v")

    assert device.made_dirs == ["/Documents/Star Trek/Season 3"]
    assert device.pushed == [("/local/ep.m4v", "/Documents/Star Trek/Season 3/ep.m4v")]


def test_remove_file_anchors_at_documents():
    """remove_file targets the /Documents-anchored path."""
    device = FakeAfcDevice(_TREE)
    manager = IPadStorageManager(device, "com.firecore.infuse")

    manager.remove_file("Movie.m4v")

    assert device.removed == ["/Documents/Movie.m4v"]


def test_free_space_uses_lockdown_disk_usage():
    """free_space_bytes returns the device-wide immediately-available figure."""
    device = FakeAfcDevice(
        _TREE, disk_usage=DiskUsage(total_capacity=256_000_000_000, available=2048)
    )
    manager = IPadStorageManager(device, "com.firecore.infuse")

    assert manager.free_space_bytes() == 2048
