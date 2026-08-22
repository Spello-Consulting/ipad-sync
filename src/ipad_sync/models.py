"""Shared data models for ipad-sync.

These lightweight dataclasses are the reusable data objects passed between the
command layer, the storage managers and the console renderer. Keeping them free
of any device or filesystem logic lets the comparison and command code be unit
tested without an iPad attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppInfo:
    """Describes a single application installed on the iPad.

    Attributes:
        bundle_id: The app's ``CFBundleIdentifier`` (e.g. ``com.firecore.infuse``).
        display_name: The user-facing name (``CFBundleDisplayName``), falling back
            to the bundle id when the display name is not reported.
    """

    bundle_id: str
    display_name: str


@dataclass
class MediaItem:
    """A single media file, identified by its path relative to a media root.

    The relative path is the cross-machine matching key: the same file on the
    iPad and on any Mac shares the same ``rel_path`` even though the absolute
    location differs per machine.

    Attributes:
        rel_path: POSIX path relative to the media root (Infuse Documents root on
            the iPad, or ``AppleTV.MediaFolder`` on the Mac). Always uses ``/``.
        size: File size in bytes. ``0`` when the file is missing.
        name: Optional human-friendly name (e.g. the playlist track name). Falls
            back to the basename of ``rel_path`` when not supplied.
        abs_path: Optional absolute path on the current machine, when known.
        missing: True when the item is referenced (e.g. by the playlist) but the
            underlying file does not exist on disk.
        show: TV show name for TV-episode tracks; ``None`` for movies/unknown.
    """

    rel_path: str
    size: int = 0
    name: str | None = None
    abs_path: str | None = None
    missing: bool = False
    show: str | None = None

    @property
    def display_name(self) -> str:
        """A friendly identifier: ``"Show - Episode"`` for TV, else the name.

        Uses ``name`` (falling back to the basename of ``rel_path``), prefixed
        with the TV ``show`` when present.
        """
        base = self.name or self.rel_path.rsplit("/", 1)[-1]
        if self.show:
            return f"{self.show} - {base}"
        return base


@dataclass
class CompareResult:
    """The difference between a playlist and the iPad's contents.

    All lists are keyed on relative path so the same object serves both sync
    directions. ``to_copy``/``to_delete`` are expressed from the iPad's point of
    view (what would change on the iPad for ``to-ipad``); the ``to-playlist``
    command interprets the same fields in reverse.

    Attributes:
        to_copy: Items present in the source but not on the iPad.
        to_delete: Items present on the iPad but not in the source.
        in_sync: Items present in both (matched by relative path).
        missing_source: Source items whose underlying file is missing from disk.
    """

    to_copy: list[MediaItem] = field(default_factory=list)
    to_delete: list[MediaItem] = field(default_factory=list)
    in_sync: list[MediaItem] = field(default_factory=list)
    missing_source: list[MediaItem] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True when applying this result would add or remove any file."""
        return bool(self.to_copy or self.to_delete)


@dataclass
class PlaylistUpdate:
    """The changes needed to make the Apple TV playlist mirror the iPad.

    All lists are keyed on relative path. Expressed from the playlist's point of
    view: what would be added to or removed from the playlist.

    Attributes:
        to_add: iPad files not in the playlist whose media exists on this Mac
            (``abs_path`` is the full path to add).
        to_remove: Playlist tracks to drop — either absent from the iPad or
            missing from this Mac's media folder.
        in_sync: Tracks already correct (on the iPad, in the playlist, present
            on this Mac); left untouched to preserve play order.
        missing_on_mac: iPad files that would be added but whose media is absent
            from this Mac's media folder, so they are skipped.
    """

    to_add: list[MediaItem] = field(default_factory=list)
    to_remove: list[MediaItem] = field(default_factory=list)
    in_sync: list[MediaItem] = field(default_factory=list)
    missing_on_mac: list[MediaItem] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True when applying this update would add or remove any track."""
        return bool(self.to_add or self.to_remove)
