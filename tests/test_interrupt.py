"""Tests for interrupt handling."""

import os
import signal
import time

from ipad_sync.interrupt import InterruptFlag, handle_interrupts


def _wait_until_set(flag: InterruptFlag, timeout: float = 1.0) -> bool:
    """Spin briefly until the flag is set (signal handlers run between bytecodes).

    Returns:
        True if the flag became set within the timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if flag:
            return True
        time.sleep(0.005)
    return bool(flag)


def test_interrupt_flag_starts_unset_then_sets():
    """The flag is falsy until set()."""
    flag = InterruptFlag()
    assert not flag
    flag.set()
    assert flag


def test_handle_interrupts_catches_sigint():
    """SIGINT sets the flag rather than raising KeyboardInterrupt."""
    messages: list[str] = []
    with handle_interrupts(lambda msg, _level: messages.append(msg)) as flag:
        os.kill(os.getpid(), signal.SIGINT)
        assert _wait_until_set(flag) is True
    assert any("SIGINT" in m for m in messages)


def test_handle_interrupts_catches_sigterm():
    """SIGTERM is caught (would otherwise terminate the process)."""
    with handle_interrupts() as flag:
        os.kill(os.getpid(), signal.SIGTERM)
        assert _wait_until_set(flag) is True


def test_handle_interrupts_restores_previous_handlers():
    """The prior signal handlers are restored on exit."""
    before_int = signal.getsignal(signal.SIGINT)
    before_term = signal.getsignal(signal.SIGTERM)
    with handle_interrupts():
        pass
    assert signal.getsignal(signal.SIGINT) is before_int
    assert signal.getsignal(signal.SIGTERM) is before_term
