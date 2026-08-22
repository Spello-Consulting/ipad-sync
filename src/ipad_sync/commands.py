"""Command implementations.

Each command function returns its reusable data object and separately renders
user-facing output via the logger, so higher-level commands can consume the data
of lower-level ones. Phase 1 implements ``ipad-apps``; further commands are added
in later phases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ipad_sync.console import render_app_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from ipad_sync.models import AppInfo
    from ipad_sync.startup import StartupResult


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
