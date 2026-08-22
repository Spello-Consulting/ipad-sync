"""Read/write access to the Apple TV sync playlist via AppleScript.

AppleScript is used only for the minimal data pull/push; all parsing and path
conversion happens in Python. Phase 1 implements the playlist existence probe
used by the startup checks plus the pure HFS->POSIX conversion helper; playlist
reading and writing are added in later phases.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - osascript is a trusted, fixed local binary
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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
    return "/Volumes/" + "/".join(parts)


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
