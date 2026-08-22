"""Command implementations.

Each command function returns its reusable data object and separately renders
user-facing output via the logger, so higher-level commands can consume the data
of lower-level ones (e.g. ``compare`` reuses ``list-playlist`` and ``list-ipad``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ipad_sync.compare import compare
from ipad_sync.console import render_app_list, render_compare, render_media_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from ipad_sync.appletv.playlist import PlaylistService
    from ipad_sync.models import AppInfo, CompareResult, MediaItem
    from ipad_sync.startup import StartupResult
    from ipad_sync.storage.base import StorageManager


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
    items = playlist.read()
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
    items = storage.list_files()
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
    playlist_items = playlist.read()
    ipad_items = storage.list_files()
    result = compare(playlist_items, ipad_items)
    log(render_compare(result), "summary")
    return result
