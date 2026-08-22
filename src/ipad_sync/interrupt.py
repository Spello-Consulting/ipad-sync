"""Clean cancellation on SIGINT (Ctrl-C) / SIGTERM.

Long-running commands (notably ``to-ipad``) check an :class:`InterruptFlag`
between files and stop gracefully instead of crashing with a traceback or
corrupting the AFC stream. The handler only *sets* the flag — it never raises —
so an in-flight file transfer finishes before the loop notices and stops.
"""

from __future__ import annotations

import signal
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import FrameType


class InterruptFlag:
    """A one-way flag set when an interrupt signal is received."""

    def __init__(self) -> None:
        """Create an unset flag."""
        self._interrupted = False

    def __bool__(self) -> bool:
        """Return whether an interrupt has been requested."""
        return self._interrupted

    def set(self) -> None:
        """Mark that an interrupt has been requested."""
        self._interrupted = True


@contextmanager
def handle_interrupts(
    log: Callable[[str, str], None] | None = None,
) -> Iterator[InterruptFlag]:
    """Install SIGINT/SIGTERM handlers that request a graceful stop.

    Restores the previous handlers on exit. Must be entered from the main thread.

    Args:
        log: Optional ``(message, verbosity)`` callable used to note the signal.

    Yields:
        An :class:`InterruptFlag` that becomes truthy once a signal arrives.
    """
    flag = InterruptFlag()

    def _handler(signum: int, _frame: FrameType | None) -> None:
        flag.set()
        if log is not None:
            name = signal.Signals(signum).name
            log(
                f"{name} received — finishing the current file, then stopping...",
                "warning",
            )

    previous = {
        signal.SIGINT: signal.signal(signal.SIGINT, _handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, _handler),
    }
    try:
        yield flag
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
