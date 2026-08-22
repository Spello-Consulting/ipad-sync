"""Pure comparison logic between a playlist and the iPad's contents.

The comparison is a set difference keyed on relative path — the cross-machine
matching key. It has no device or filesystem dependencies so it is trivially
unit tested, and its :class:`~ipad_sync.models.CompareResult` is reused by both
the ``to-ipad`` and ``to-playlist`` commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ipad_sync.models import CompareResult

if TYPE_CHECKING:
    from ipad_sync.models import MediaItem


def compare(
    playlist_items: list[MediaItem], ipad_items: list[MediaItem]
) -> CompareResult:
    """Compare playlist media against iPad media by relative path.

    A playlist item and an iPad item match when their ``rel_path`` values are
    equal. Playlist items whose source file is missing from disk are reported
    separately and are never scheduled for copying, but they still count as
    "in the playlist" so a matching iPad file is not deleted.

    Args:
        playlist_items: Items read from the Apple TV playlist.
        ipad_items: Items present in the iPad app's Documents.

    Returns:
        A :class:`CompareResult` where ``to_copy``/``to_delete`` are expressed
        from the iPad's point of view (what ``to-ipad`` would change).
    """
    ipad_by_rel = {item.rel_path: item for item in ipad_items}
    playlist_rels = {item.rel_path for item in playlist_items}

    result = CompareResult()
    for item in playlist_items:
        if item.missing:
            result.missing_source.append(item)
        elif item.rel_path in ipad_by_rel:
            result.in_sync.append(item)
        else:
            result.to_copy.append(item)

    result.to_delete = [
        item for item in ipad_items if item.rel_path not in playlist_rels
    ]
    return result
