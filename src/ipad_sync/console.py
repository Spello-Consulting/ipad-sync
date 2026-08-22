"""User-facing rendering and prompt helpers.

Rendering functions are pure — they build display strings so they can be unit
tested without capturing stdout. The command layer passes the result to the
logger (which honours the configured console/logfile verbosity).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ipad_sync.models import AppInfo

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
