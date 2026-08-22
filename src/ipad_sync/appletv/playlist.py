"""Read/write access to the Apple TV sync playlist via AppleScript.

AppleScript is used only for the minimal data pull/push; all parsing and path
conversion happens in Python. This module provides the playlist existence probe,
the pure HFS->POSIX conversion helper and bulk playlist reading; playlist writing
is added in a later phase.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - osascript is a trusted, fixed local binary
import tempfile
from itertools import zip_longest
from pathlib import Path
from typing import TYPE_CHECKING

from ipad_sync.models import MediaItem

_VOLUMES_PREFIX = "/Volumes/"

if TYPE_CHECKING:
    from collections.abc import Callable

# Delimiters emitted by read_playlist.applescript (must match that script).
_GROUP_SEP = "\x1d"  # ASCII 29: separates the names blob from the locations blob
_RECORD_SEP = "\x1e"  # ASCII 30: separates entries within a blob

# AppleScript coerces a null `location` (e.g. a deleted file) to this string.
_MISSING_LOCATION = "missing value"


class PlaylistError(Exception):
    """Raised when an AppleScript playlist operation fails."""


def hfs_to_posix(hfs_path: str) -> str:
    """Convert an HFS (colon-delimited) path to a POSIX path.

    AppleScript reports a track's location as an HFS path string such as
    ``Data_IT:Multimedia:Video:Movie.m4v``; this maps it to
    ``/Volumes/Data_IT/Multimedia/Video/Movie.m4v``.

    Args:
        hfs_path: The colon-delimited HFS path (a trailing ``:`` is tolerated).

    Returns:
        The equivalent POSIX path under ``/Volumes``.

    Raises:
        ValueError: If ``hfs_path`` is empty.
    """
    trimmed = hfs_path.rstrip(":")
    if not trimmed:
        msg = "Cannot convert an empty HFS path."
        raise ValueError(msg)
    parts = trimmed.split(":")
    return _VOLUMES_PREFIX + "/".join(parts)


def posix_to_hfs(posix_path: str) -> str:
    """Convert a POSIX ``/Volumes`` path to an HFS (colon-delimited) path.

    The inverse of :func:`hfs_to_posix`, used to match a track's stored location
    string when removing it from a playlist.

    Args:
        posix_path: A POSIX path under ``/Volumes``.

    Returns:
        The equivalent HFS path (e.g. ``Data_IT:Multimedia:Video:Movie.m4v``).

    Raises:
        ValueError: If ``posix_path`` is not under ``/Volumes`` or is empty.
    """
    if not posix_path.startswith(_VOLUMES_PREFIX):
        msg = f"Cannot convert a POSIX path outside /Volumes to HFS: {posix_path}"
        raise ValueError(msg)
    remainder = posix_path[len(_VOLUMES_PREFIX) :].rstrip("/")
    if not remainder:
        msg = "Cannot convert an empty POSIX path."
        raise ValueError(msg)
    return remainder.replace("/", ":")


class PlaylistService:
    """AppleScript-backed access to a named playlist in the macOS TV app."""

    def __init__(
        self,
        playlist_name: str,
        media_folder: Path,
        script_dir: Path,
        log: Callable[[str, str], None] | None = None,
    ) -> None:
        """Create the service.

        Args:
            playlist_name: Name of the playlist (e.g. ``"iPad Sync"``).
            media_folder: The Apple TV media root on this machine.
            script_dir: Directory containing the ``.applescript`` files.
            log: Optional ``(message, verbosity)`` logging callable.
        """
        self._playlist_name = playlist_name
        self._media_folder = media_folder
        self._script_dir = script_dir
        self._log = log

    def _run_script(self, script_name: str, *args: str) -> str:
        """Run an AppleScript file with ``osascript`` and return its stdout.

        Args:
            script_name: Filename of the script within ``script_dir``.
            *args: Arguments passed to the script's ``on run argv`` handler.

        Returns:
            The script's standard output, stripped of trailing whitespace.

        Raises:
            PlaylistError: If the script is missing or ``osascript`` fails.
        """
        script_path = self._script_dir / script_name
        if not script_path.is_file():
            msg = f"AppleScript not found: {script_path}"
            raise PlaylistError(msg)
        try:
            result = subprocess.run(  # noqa: S603 - fixed binary, no shell
                ["/usr/bin/osascript", str(script_path), *args],
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            msg = "osascript not found; this command requires macOS."
            raise PlaylistError(msg) from exc
        except subprocess.CalledProcessError as exc:
            msg = f"AppleScript '{script_name}' failed: {exc.stderr.strip()}"
            raise PlaylistError(msg) from exc
        return result.stdout.strip()

    def get_name(self) -> str:
        """Return the configured playlist name.

        Returns:
            The playlist name (e.g. ``"iPad Sync"``).
        """
        return self._playlist_name

    def exists(self) -> bool:
        """Return whether the playlist currently exists in the TV app.

        Returns:
            True if a playlist with the configured name exists.
        """
        output = self._run_script("playlist_exists.applescript", self._playlist_name)
        return output == "1"

    def read(self) -> list[MediaItem]:
        """Read the playlist's file tracks as media items.

        Each track's HFS location is converted to a POSIX path, made relative to
        the configured media folder, and checked on disk for existence and size.

        Returns:
            One :class:`MediaItem` per file track, in playlist order. Items whose
            file is absent from disk are flagged ``missing`` (with ``size`` 0).
        """
        output = self._run_script("read_playlist.applescript", self._playlist_name)
        return self._parse(output)

    def _parse(self, output: str) -> list[MediaItem]:
        """Parse the AppleScript blob into media items.

        Returns:
            The parsed media items (empty when the blob is empty).
        """
        if not output:
            return []
        names_blob, _, rest = output.partition(_GROUP_SEP)
        locs_blob, _, shows_blob = rest.partition(_GROUP_SEP)
        names = names_blob.split(_RECORD_SEP) if names_blob else []
        locations = locs_blob.split(_RECORD_SEP) if locs_blob else []
        shows = shows_blob.split(_RECORD_SEP) if shows_blob else []

        items: list[MediaItem] = []
        for name, hfs, raw_show in zip_longest(names, locations, shows, fillvalue=""):
            show = self._clean_show(raw_show)
            # A deleted/unavailable media file makes AppleScript report the
            # track's location as "missing value"; keep the track name (and TV
            # show) so the user can still identify it.
            if hfs.strip().casefold() == _MISSING_LOCATION:
                if self._log is not None:
                    label = f"{show} - {name}" if show else name
                    self._log(
                        f"Playlist track '{label}' has no media file (deleted or unavailable).",
                        "warning",
                    )
                items.append(
                    MediaItem(
                        rel_path=name,
                        size=0,
                        name=name,
                        abs_path=None,
                        missing=True,
                        show=show,
                    )
                )
                continue
            posix = hfs_to_posix(hfs)
            exists, size = self._stat_path(posix)
            items.append(
                MediaItem(
                    rel_path=self._relative_to_root(posix),
                    size=size,
                    name=name,
                    abs_path=posix,
                    missing=not exists,
                    show=show,
                )
            )
        return items

    @staticmethod
    def _clean_show(raw_show: str) -> str | None:
        """Normalise a raw ``show`` value to a TV show name or ``None``.

        Returns:
            The trimmed show name, or ``None`` for movies (empty / "missing value").
        """
        value = raw_show.strip()
        if not value or value.casefold() == _MISSING_LOCATION:
            return None
        return value

    @staticmethod
    def _stat_path(posix_path: str) -> tuple[bool, int]:
        """Return ``(exists, size)`` for a media file on the local machine.

        Returns:
            A ``(exists, size_in_bytes)`` tuple; ``(False, 0)`` when absent.
        """
        path = Path(posix_path)
        if path.is_file():
            return True, path.stat().st_size
        return False, 0

    def _relative_to_root(self, posix_path: str) -> str:
        """Return ``posix_path`` relative to the media folder (POSIX style).

        Falls back to the absolute path (which simply won't match any iPad entry)
        when the file lies outside the configured media folder.
        """
        try:
            return Path(posix_path).relative_to(self._media_folder).as_posix()
        except ValueError:
            if self._log is not None:
                self._log(
                    f"Playlist track is outside the media folder, cannot map: {posix_path}",
                    "warning",
                )
            return posix_path

    def add_tracks(self, posix_paths: list[str]) -> int:
        """Add media files to the playlist by POSIX path (creating it if absent).

        Args:
            posix_paths: Full POSIX paths of media files to add.

        Returns:
            The number of tracks added.
        """
        if not posix_paths:
            return 0
        output = self._run_script_with_list("add_to_playlist.applescript", posix_paths)
        return int(output or "0")

    def remove_tracks(self, posix_paths: list[str]) -> int:
        """Remove tracks whose stored location matches the given POSIX paths.

        Args:
            posix_paths: Full POSIX paths (as read from the playlist) to remove.

        Returns:
            The number of tracks removed.
        """
        if not posix_paths:
            return 0
        hfs_locations = [posix_to_hfs(path) for path in posix_paths]
        output = self._run_script_with_list(
            "remove_from_playlist.applescript", hfs_locations
        )
        return int(output or "0")

    def _run_script_with_list(self, script_name: str, lines: list[str]) -> str:
        """Run a script passing a UTF-8, newline-delimited temp file of ``lines``.

        Args:
            script_name: The ``.applescript`` file to run.
            lines: Lines to write to the temp file (the script's second argument).

        Returns:
            The script's stdout, stripped.
        """
        with tempfile.NamedTemporaryFile(
            "w", prefix="ipad-sync-", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("\n".join(lines))
            tmp_path = Path(handle.name)
        try:
            return self._run_script(script_name, self._playlist_name, str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
