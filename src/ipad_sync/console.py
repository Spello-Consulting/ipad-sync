"""User-facing rendering and prompt helpers.

Rendering functions are pure — they build display strings so they can be unit
tested without capturing stdout. The command layer passes the result to the
logger (which honours the configured console/logfile verbosity).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ipad_sync.models import AppInfo, CompareResult, MediaItem

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Args:
        num_bytes: The size in bytes.

    Returns:
        A string such as ``"1.5 GB"`` or ``"512 B"``.
    """
    size = float(num_bytes)
    for unit in _UNITS:
        if abs(size) < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    # Unreachable, but keeps type checkers satisfied.
    return f"{num_bytes} B"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as ``h:mm:ss`` or ``mm:ss``.

    Args:
        seconds: The duration in seconds.

    Returns:
        A compact clock-style string (e.g. ``"3:07"`` or ``"1:02:09"``).
    """
    total = max(int(seconds), 0)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_progress(done_bytes: int, total_bytes: int, elapsed_seconds: float) -> str:
    """Format copy progress with percentage, throughput and an ETA.

    Args:
        done_bytes: Bytes transferred so far.
        total_bytes: Total bytes to transfer.
        elapsed_seconds: Seconds elapsed since the transfer started.

    Returns:
        A one-line progress string.
    """
    pct = (done_bytes / total_bytes * 100) if total_bytes else 100.0
    parts = [f"{pct:.0f}%  {format_size(done_bytes)} / {format_size(total_bytes)}"]
    if done_bytes and elapsed_seconds > 0:
        rate = done_bytes / elapsed_seconds
        if rate > 0:
            remaining = max(total_bytes - done_bytes, 0)
            parts.append(
                f"~{format_duration(remaining / rate)} left ({format_size(int(rate))}/s)"
            )
    return "  ".join(parts)


def render_app_list(apps: list[AppInfo]) -> str:
    """Render installed apps as an aligned two-column table.

    Args:
        apps: The apps to display (already ordered by the caller).

    Returns:
        A multi-line string with a ``Display Name`` / ``Bundle ID`` table, or a
        short notice when there are no apps.
    """
    if not apps:
        return "No applications found."

    name_header, id_header = "Display Name", "Bundle ID"
    name_width = max(len(name_header), *(len(app.display_name) for app in apps))

    lines = [
        f"{name_header:<{name_width}}  {id_header}",
        f"{'-' * name_width}  {'-' * len(id_header)}",
    ]
    lines.extend(f"{app.display_name:<{name_width}}  {app.bundle_id}" for app in apps)
    lines.extend(("", f"{len(apps)} app(s)."))
    return "\n".join(lines)


def _total_size(items: list[MediaItem]) -> int:
    """Return the summed size of all items in bytes."""
    return sum(item.size for item in items)


def render_media_list(items: list[MediaItem], title: str, empty_message: str) -> str:
    """Render media items as a table of relative path and size.

    Args:
        items: The media items to display (already ordered by the caller).
        title: A heading shown above the table.
        empty_message: Text shown instead of a table when ``items`` is empty.

    Returns:
        A multi-line string with the table and a summary footer.
    """
    if not items:
        return f"{title}\n{empty_message}"

    path_header, size_header = "Path", "Size"
    path_width = max(len(path_header), *(len(item.rel_path) for item in items))

    lines = [
        title,
        f"{path_header:<{path_width}}  {size_header:>10}",
        f"{'-' * path_width}  {'-' * 10}",
    ]
    for item in items:
        size_text = "MISSING" if item.missing else format_size(item.size)
        lines.append(f"{item.rel_path:<{path_width}}  {size_text:>10}")
    lines.append(f"\n{len(items)} file(s), {format_size(_total_size(items))} total.")
    return "\n".join(lines)


def render_compare(result: CompareResult) -> str:
    """Render a comparison result as a human-readable summary.

    Args:
        result: The comparison to summarise.

    Returns:
        A multi-line string describing copies, deletions, matches and any
        missing source files.
    """
    lines = ["Comparison (playlist vs iPad):"]

    copy_size = format_size(_total_size(result.to_copy))
    delete_size = format_size(_total_size(result.to_delete))
    lines.extend((
        f"  To copy to iPad:   {len(result.to_copy)} file(s), {copy_size}",
        f"  To delete on iPad: {len(result.to_delete)} file(s), {delete_size}",
        f"  Already in sync:   {len(result.in_sync)} file(s)",
    ))

    lines.extend(
        f"    + {item.rel_path} ({format_size(item.size)})" for item in result.to_copy
    )
    lines.extend(
        f"    - {item.rel_path} ({format_size(item.size)})" for item in result.to_delete
    )

    if result.missing_source:
        lines.append(
            f"  Missing from media folder (cannot copy): {len(result.missing_source)}"
        )
        lines.extend(f"    ! {item.rel_path}" for item in result.missing_source)

    if not result.has_changes:
        lines.append("  Nothing to do — iPad already matches the playlist.")
    return "\n".join(lines)


def confirm(prompt: str, assume_yes: bool = False) -> bool:
    """Ask the user a yes/no question on the console.

    Args:
        prompt: The question to display (a ``" [y/N]: "`` suffix is appended).
        assume_yes: When True, skip the prompt and return True (for ``--yes``).

    Returns:
        True if the user answered yes (or ``assume_yes`` is set); False otherwise,
        including when stdin is not interactive.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{prompt} [y/N]: ").strip().casefold()
    except EOFError:
        return False
    return answer in {"y", "yes"}
