"""Command implementations.

Each command function returns its reusable data object and separately renders
user-facing output via the logger, so higher-level commands can consume the data
of lower-level ones (e.g. ``compare`` reuses ``list-playlist`` and ``list-ipad``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from ipad_sync.compare import compare
from ipad_sync.console import (
    confirm,
    format_progress,
    format_size,
    render_app_list,
    render_compare,
    render_media_list,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ipad_sync.appletv.playlist import PlaylistService
    from ipad_sync.models import AppInfo, CompareResult, MediaItem
    from ipad_sync.startup import StartupResult
    from ipad_sync.storage.base import StorageManager

# 1 GiB, used to convert the configured minimum-free-space (GB) to bytes.
_BYTES_PER_GB = 1024**3


def _read_playlist(
    playlist: PlaylistService,
    log: Callable[[str, str], None],
) -> list[MediaItem]:
    """Read the playlist, logging progress first.

    Returns:
        The playlist media items.
    """
    log("Reading Apple TV playlist...", "summary")
    return playlist.read()


def _read_ipad(
    storage: StorageManager,
    log: Callable[[str, str], None],
) -> list[MediaItem]:
    """List the iPad documents, logging progress first.

    Returns:
        The iPad media items.
    """
    log("Reading iPad documents...", "summary")
    return storage.list_files()


def cmd_ipad_apps(
    startup: StartupResult,
    log: Callable[[str, str], None],
) -> list[AppInfo]:
    """List the apps installed on the iPad with display name and bundle id.

    The app list is gathered during startup; this command renders it.

    Args:
        startup: The startup result carrying the loaded app list.
        log: ``(message, verbosity)`` logging callable.

    Returns:
        The list of :class:`AppInfo` (also the data reused by startup).
    """
    apps = startup.apps
    log(render_app_list(apps), "summary")
    return apps


def cmd_list_playlist(
    playlist: PlaylistService,
    log: Callable[[str, str], None],
) -> list[MediaItem]:
    """List the Apple TV playlist's file tracks.

    Args:
        playlist: The playlist service to read from.
        log: ``(message, verbosity)`` logging callable.

    Returns:
        The playlist media items (reused by ``compare`` and ``to-ipad``).
    """
    items = _read_playlist(playlist, log)
    log(
        render_media_list(items, "Apple TV playlist:", "  (playlist is empty)"),
        "summary",
    )
    return items


def cmd_list_ipad(
    storage: StorageManager,
    log: Callable[[str, str], None],
) -> list[MediaItem]:
    """List the files in the iPad app's Documents.

    Args:
        storage: A connected storage manager.
        log: ``(message, verbosity)`` logging callable.

    Returns:
        The iPad media items (reused by ``compare`` and ``to-playlist``).
    """
    items = _read_ipad(storage, log)
    log(render_media_list(items, "iPad Documents:", "  (no files on iPad)"), "summary")
    return items


def cmd_compare(
    playlist: PlaylistService,
    storage: StorageManager,
    log: Callable[[str, str], None],
) -> CompareResult:
    """Compare the playlist against the iPad's contents by relative path.

    Args:
        playlist: The playlist service to read from.
        storage: A connected storage manager.
        log: ``(message, verbosity)`` logging callable.

    Returns:
        The :class:`CompareResult` (reused by ``to-ipad`` and ``to-playlist``).
    """
    playlist_items = _read_playlist(playlist, log)
    ipad_items = _read_ipad(storage, log)
    result = compare(playlist_items, ipad_items)
    log(render_compare(result), "summary")
    return result


def _apply_deletes(
    result: CompareResult,
    storage: StorageManager,
    log: Callable[[str, str], None],
) -> None:
    """Remove the iPad files scheduled for deletion (deletes run before copies)."""
    if not result.to_delete:
        return
    total = len(result.to_delete)
    log(f"Deleting {total} file(s) from the iPad...", "summary")
    for index, item in enumerate(result.to_delete, start=1):
        log(f"  [{index}/{total}] removing {item.rel_path}", "detailed")
        storage.remove_file(item.rel_path)


def _apply_copies(
    result: CompareResult,
    storage: StorageManager,
    log: Callable[[str, str], None],
) -> None:
    """Copy the playlist files scheduled for addition, reporting progress."""
    if not result.to_copy:
        return
    total = len(result.to_copy)
    total_bytes = sum(item.size for item in result.to_copy)
    log(
        f"Copying {total} file(s) to the iPad ({format_size(total_bytes)})...",
        "summary",
    )

    done_bytes = 0
    start = time.monotonic()
    for index, item in enumerate(result.to_copy, start=1):
        if item.abs_path is None:
            log(
                f"  [{index}/{total}] skipping {item.rel_path}: no source path",
                "warning",
            )
            continue
        log(
            f"  [{index}/{total}] {item.rel_path} ({format_size(item.size)})", "summary"
        )
        storage.push_file(Path(item.abs_path), item.rel_path)
        done_bytes += item.size
        log(
            "  " + format_progress(done_bytes, total_bytes, time.monotonic() - start),
            "summary",
        )


def cmd_to_ipad(
    playlist: PlaylistService,
    storage: StorageManager,
    log: Callable[[str, str], None],
    *,
    min_free_gb: int = 1,
    assume_yes: bool = False,
) -> bool:
    """Mirror the Apple TV playlist media onto the iPad.

    Runs a comparison, checks the projected free space against the minimum,
    confirms with the user, then deletes extras before copying new files while
    preserving relative paths.

    Args:
        playlist: The playlist service to read from.
        storage: A connected storage manager.
        log: ``(message, verbosity)`` logging callable.
        min_free_gb: Minimum free space to preserve on the iPad, in GB.
        assume_yes: When True, skip the confirmation prompt.

    Returns:
        True if the sync was applied (or nothing needed doing); False if it was
        aborted (empty playlist, insufficient space, or the user declined).
    """
    playlist_items = _read_playlist(playlist, log)
    if not playlist_items:
        log(
            "Apple TV playlist is empty; refusing to sync (this would erase the iPad).",
            "error",
        )
        return False

    ipad_items = _read_ipad(storage, log)
    result = compare(playlist_items, ipad_items)
    log(render_compare(result), "summary")

    add_bytes = sum(item.size for item in result.to_copy)
    freed_bytes = sum(item.size for item in result.to_delete)
    free_now = storage.free_space_bytes()
    projected_free = free_now + freed_bytes - add_bytes
    min_free = min_free_gb * _BYTES_PER_GB
    log(
        f"Space: {format_size(free_now)} free now; "
        f"{format_size(projected_free)} after sync (minimum {format_size(min_free)}).",
        "summary",
    )
    if projected_free < min_free:
        log(
            f"Not enough space on the iPad: the sync would leave {format_size(projected_free)}, "
            f"below the {format_size(min_free)} minimum. Aborting.",
            "error",
        )
        return False

    if result.missing_source:
        log(
            f"{len(result.missing_source)} playlist file(s) are missing from the media "
            "folder and will be skipped.",
            "warning",
        )

    if not result.has_changes:
        log("iPad already matches the playlist; nothing to do.", "summary")
        return True

    if not confirm(
        f"Proceed? {len(result.to_delete)} to delete, {len(result.to_copy)} to copy.",
        assume_yes,
    ):
        log("Aborted by user.", "summary")
        return False

    _apply_deletes(result, storage, log)
    _apply_copies(result, storage, log)
    log("Sync to iPad complete.", "summary")
    return True
