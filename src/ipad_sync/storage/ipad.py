"""Device-backed storage manager for an iPad app's Documents folder.

Wraps an :class:`~ipad_sync.device.IPadDevice` (the synchronous facade over
``pymobiledevice3``) so the rest of the app treats iPad storage exactly like the
simulation backend.
"""

from __future__ import annotations

import posixpath
import stat
from typing import TYPE_CHECKING

from ipad_sync.models import MediaItem
from ipad_sync.storage.base import StorageManager

if TYPE_CHECKING:
    from pathlib import Path

    from ipad_sync.device import IPadDevice
    from ipad_sync.storage.base import ProgressCallback

# With ``documents_only`` House Arrest (VendDocuments), the AFC session is rooted
# at the app container and only the ``Documents`` subtree is accessible; listing
# "/" itself returns PERM_DENIED. All paths are therefore anchored here.
_DOCUMENTS_ROOT = "/Documents"


class IPadStorageManager(StorageManager):
    """A :class:`StorageManager` backed by an iPad app's Documents over AFC.

    The manager does not own the connection lifecycle of the device itself: the
    :class:`IPadDevice` is created and connected during startup (so trust dialogs
    appear up front) and passed in here. :meth:`connect` opens the House Arrest
    (Documents) session for the target app; :meth:`close` releases it.
    """

    def __init__(self, device: IPadDevice, bundle_id: str) -> None:
        """Create the manager.

        Args:
            device: A connected :class:`IPadDevice`.
            bundle_id: Bundle id of the app whose Documents to manage.
        """
        self._device = device
        self._bundle_id = bundle_id

    def connect(self) -> None:
        """Open the Documents AFC session for the target app."""
        self._device.open_documents(self._bundle_id)

    def close(self) -> None:
        """Close the underlying device session."""
        self._device.close()

    def list_files(self) -> list[MediaItem]:
        """Recursively list every file in Documents, relative to its root.

        Returns:
            One :class:`MediaItem` per file, sorted by relative path.
        """
        items: list[MediaItem] = []
        self._walk(_DOCUMENTS_ROOT, items)
        items.sort(key=lambda item: item.rel_path)
        return items

    def _walk(self, path: str, items: list[MediaItem]) -> None:
        """Depth-first walk accumulating file entries into ``items``."""
        for name in self._device.afc_listdir(path):
            # Skip hidden entries such as Infuse's ".Trash" folder of deleted
            # files, which must not count as iPad content.
            if name.startswith("."):
                continue
            child = posixpath.join(path, name)
            info = self._device.afc_stat(child)
            if stat.S_ISDIR(info.st_mode):
                self._walk(child, items)
            else:
                rel = posixpath.relpath(child, _DOCUMENTS_ROOT)
                items.append(MediaItem(rel_path=rel, size=info.st_size))

    def free_space_bytes(self) -> int:
        """Return the iPad's immediately-writable free storage in bytes.

        Uses the device-wide lockdown ``disk_usage`` figure (the same value
        reported during startup) so the ``to-ipad`` space-fit guard and the
        startup report never disagree. This is the space available for transfers
        right now; iOS *Settings* may show more because it counts reclaimable
        purgeable storage that is not exposed here.

        Returns:
            The free space in bytes.
        """
        return self._device.disk_usage().available

    def push_file(
        self,
        local_path: Path,
        rel_path: str,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Upload ``local_path`` into Documents at ``rel_path``.

        Intermediate directories are created first so the relative layout is
        preserved on the iPad.

        Args:
            local_path: Source file on the local machine.
            rel_path: Destination POSIX path relative to the Documents root.
            on_progress: Optional ``(bytes_transferred, total_bytes)`` callback.
        """
        remote = posixpath.join(_DOCUMENTS_ROOT, rel_path)
        parent = posixpath.dirname(remote)
        if parent:
            self._device.afc_makedirs(parent)
        self._device.afc_push(str(local_path), remote)
        if on_progress is not None:
            size = local_path.stat().st_size
            on_progress(size, size)

    def remove_file(self, rel_path: str) -> None:
        """Delete ``rel_path`` from Documents.

        Args:
            rel_path: POSIX path relative to the Documents root.
        """
        self._device.afc_rm(posixpath.join(_DOCUMENTS_ROOT, rel_path))
