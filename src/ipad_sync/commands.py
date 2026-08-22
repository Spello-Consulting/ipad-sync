"""Command implementations.

Each command function returns its reusable data object and separately renders
user-facing output via the logger, so higher-level commands can consume the data
of lower-level ones (e.g. ``compare`` reuses ``list-playlist`` and ``list-ipad``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from ipad_sync.compare import compare, plan_playlist_update
from ipad_sync.console import (
    confirm,
    format_progress,
    format_size,
    render_app_list,
    render_compare,
    render_media_list,
    render_playlist_update,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ipad_sync.appletv.playlist import PlaylistService
    from ipad_sync.models import AppInfo, CompareResult, MediaItem
    from ipad_sync.startup import StartupResult
    from ipad_sync.storage.base import StorageManager

# 1 GiB, used to convert the configured minimum-free-space (GB) to bytes.
_BYTES_PER_GB = 1024**3


def _never_abort() -> bool:
    """Default ``should_abort`` predicate: never requests a stop.

    Returns:
        Always ``False``.
    """
    return False


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
    should_abort: Callable[[], bool],
) -> bool:
    """Remove the iPad files scheduled for deletion (deletes run before copies).

    Returns:
        True if all deletions completed; False if interrupted.
    """
    if not result.to_delete:
        return True
    total = len(result.to_delete)
    log(f"Deleting {total} file(s) from the iPad...", "summary")
    for index, item in enumerate(result.to_delete, start=1):
        if should_abort():
            log(f"Interrupted before deleting {item.rel_path}; stopping.", "warning")
            return False
        log(f"  [{index}/{total}] removing {item.rel_path}", "detailed")
        storage.remove_file(item.rel_path)
    return True


def _apply_copies(
    result: CompareResult,
    storage: StorageManager,
    log: Callable[[str, str], None],
    should_abort: Callable[[], bool],
) -> bool:
    """Copy the playlist files scheduled for addition, reporting progress.

    The interrupt flag is checked between files so an in-flight transfer always
    finishes and no partial file is left behind.

    Returns:
        True if all copies completed; False if interrupted.
    """
    if not result.to_copy:
        return True
    total = len(result.to_copy)
    total_bytes = sum(item.size for item in result.to_copy)
    log(
        f"Copying {total} file(s) to the iPad ({format_size(total_bytes)})...",
        "summary",
    )

    done_bytes = 0
    start = time.monotonic()
    for index, item in enumerate(result.to_copy, start=1):
        if should_abort():
            log(
                f"Interrupted after {index - 1} of {total} copies; stopping.", "warning"
            )
            return False
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
    return True


def cmd_to_ipad(
    playlist: PlaylistService,
    storage: StorageManager,
    log: Callable[[str, str], None],
    *,
    min_free_gb: int = 1,
    assume_yes: bool = False,
    should_abort: Callable[[], bool] = _never_abort,
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
        should_abort: Predicate polled between files to stop early (Ctrl-C).

    Returns:
        True if the sync was applied (or nothing needed doing); False if it was
        aborted (empty playlist, insufficient space, user declined, or interrupted).
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
        names = ", ".join(item.display_name for item in result.missing_source)
        log(
            f"{len(result.missing_source)} playlist file(s) missing from the media "
            f"folder and will be skipped: {names}",
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

    if not _apply_deletes(result, storage, log, should_abort):
        log("Sync interrupted during deletions; copies skipped.", "warning")
        return False
    if not _apply_copies(result, storage, log, should_abort):
        log(
            "Sync interrupted; some files were not copied. Re-run to finish.", "warning"
        )
        return False
    log("Sync to iPad complete.", "summary")
    return True


def cmd_to_playlist(
    playlist: PlaylistService,
    storage: StorageManager,
    media_folder: Path,
    log: Callable[[str, str], None],
    *,
    assume_yes: bool = False,
    should_abort: Callable[[], bool] = _never_abort,
) -> bool:
    """Rebuild the Apple TV playlist to mirror the iPad's contents.

    Does not copy media to the Mac — it only edits the playlist. Existing correct
    tracks are left in place to preserve play order; tracks absent from the iPad
    (or missing from this Mac's media folder) are removed, and iPad files whose
    media exists locally are added by full path. The playlist is created if absent.

    Args:
        playlist: The playlist service to read and write.
        storage: A connected storage manager.
        media_folder: The Apple TV media root on this machine.
        log: ``(message, verbosity)`` logging callable.
        assume_yes: When True, skip the confirmation prompt.
        should_abort: Predicate polled before mutating steps to stop early.

    Returns:
        True if the update was applied (or nothing needed doing); False if it was
        aborted (user declined or interrupted).
    """
    ipad_items = _read_ipad(storage, log)
    playlist_items = _read_playlist(playlist, log)
    update = plan_playlist_update(ipad_items, playlist_items, media_folder)
    log(render_playlist_update(update), "summary")

    if update.missing_on_mac:
        log(
            f"{len(update.missing_on_mac)} iPad file(s) are missing from the media folder "
            "and will not be added to the playlist.",
            "warning",
        )

    if not update.has_changes:
        log("Playlist already matches the iPad; nothing to do.", "summary")
        return True

    if not confirm(
        f"Proceed? {len(update.to_remove)} to remove, {len(update.to_add)} to add.",
        assume_yes,
    ):
        log("Aborted by user.", "summary")
        return False

    if should_abort():
        log("Interrupted before applying changes.", "warning")
        return False
    if update.to_remove:
        log(
            f"Removing {len(update.to_remove)} track(s) from the playlist...", "summary"
        )
        remove_paths = [item.abs_path for item in update.to_remove if item.abs_path]
        removed = playlist.remove_tracks(remove_paths)
        log(f"Removed {removed} track(s).", "summary")

    if should_abort():
        log("Interrupted after removals; additions skipped.", "warning")
        return False
    if update.to_add:
        log(f"Adding {len(update.to_add)} track(s) to the playlist...", "summary")
        add_paths = [item.abs_path for item in update.to_add if item.abs_path]
        added = playlist.add_tracks(add_paths)
        log(f"Added {added} track(s).", "summary")

    log("Playlist update complete.", "summary")
    return True
