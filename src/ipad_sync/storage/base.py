"""Storage manager base class and the simulation implementation.

All iPad Documents access goes through a :class:`StorageManager`. The abstract
base defines the synchronous contract used by the commands; the concrete
:class:`SimulationStorageManager` (backed by a local directory) implements that
contract without any device, so the whole application can be exercised and unit
tested with no iPad attached.

The real device-backed manager lives in :mod:`ipad_sync.storage.ipad`.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Self

from ipad_sync.models import MediaItem

# Progress callback: (bytes_transferred_for_this_file, total_bytes_for_this_file).
ProgressCallback = Callable[[int, int], None]


class StorageManager(ABC):
    """Abstract, synchronous interface to an app's Documents storage.

    Relative paths are always POSIX-style (``/`` separated) and rooted at the
    Documents folder, matching the cross-machine key used throughout ipad-sync.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open the storage session. Must be called before other operations."""

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the session. Safe to call repeatedly."""

    @abstractmethod
    def list_files(self) -> list[MediaItem]:
        """Return every file in Documents as a :class:`MediaItem`.

        Returns:
            One item per file (directories are not returned), each with its POSIX
            ``rel_path`` and ``size`` populated.
        """

    @abstractmethod
    def free_space_bytes(self) -> int:
        """Return the free space available in the storage area, in bytes."""

    @abstractmethod
    def push_file(
        self,
        local_path: Path,
        rel_path: str,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Copy a local file into Documents at ``rel_path``, creating parents.

        Args:
            local_path: Source file on the local machine.
            rel_path: Destination POSIX path relative to the Documents root.
            on_progress: Optional callback invoked with
                ``(bytes_transferred, total_bytes)`` as the copy proceeds.
        """

    @abstractmethod
    def remove_file(self, rel_path: str) -> None:
        """Delete the file at ``rel_path`` (relative to the Documents root)."""

    def __enter__(self) -> Self:
        """Connect on entering a ``with`` block.

        Returns:
            This storage manager.
        """
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close on leaving a ``with`` block."""
        self.close()


class SimulationStorageManager(StorageManager):
    """A :class:`StorageManager` backed by a local directory tree.

    Used both as the ``--simulate`` runtime backend and as the test double for
    every command. Free space is modelled against a configurable capacity so the
    minimum-free-space guard in ``to-ipad`` can be exercised deterministically.
    """

    #: Default simulated capacity (256 GB) when none is supplied.
    DEFAULT_CAPACITY_BYTES = 256 * 1024**3

    def __init__(self, root: Path, capacity_bytes: int | None = None) -> None:
        """Create a simulation manager.

        Args:
            root: Local directory that stands in for the Documents folder. It is
                created on :meth:`connect` if it does not exist.
            capacity_bytes: Total simulated storage capacity. Free space is
                reported as this minus the bytes currently used under ``root``.
        """
        self._root = root
        self._capacity_bytes = (
            capacity_bytes
            if capacity_bytes is not None
            else self.DEFAULT_CAPACITY_BYTES
        )
        self._connected = False

    @property
    def root(self) -> Path:
        """The local directory standing in for Documents."""
        return self._root

    def connect(self) -> None:
        """Ensure the simulation root directory exists."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._connected = True

    def close(self) -> None:
        """Mark the session closed (no resources to release)."""
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            msg = "SimulationStorageManager is not connected; call connect() first."
            raise RuntimeError(msg)

    def list_files(self) -> list[MediaItem]:
        """Return every file under the simulation root, relative to it."""
        self._require_connected()
        items: list[MediaItem] = []
        for path in sorted(self._root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(self._root).as_posix()
                items.append(MediaItem(rel_path=rel, size=path.stat().st_size))
        return items

    def _used_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._root.rglob("*") if p.is_file())

    def free_space_bytes(self) -> int:
        """Return simulated capacity minus bytes currently used (never negative)."""
        self._require_connected()
        return max(self._capacity_bytes - self._used_bytes(), 0)

    def push_file(
        self,
        local_path: Path,
        rel_path: str,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Copy ``local_path`` to ``rel_path`` under the simulation root."""
        self._require_connected()
        dest = self._root / Path(rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        if on_progress is not None:
            size = dest.stat().st_size
            on_progress(size, size)

    def remove_file(self, rel_path: str) -> None:
        """Delete ``rel_path`` and prune any directories it leaves empty."""
        self._require_connected()
        target = self._root / Path(rel_path)
        target.unlink(missing_ok=True)
        # Prune now-empty parent directories, but never the root itself.
        parent = target.parent
        while parent != self._root and parent.is_relative_to(self._root):
            if any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent
