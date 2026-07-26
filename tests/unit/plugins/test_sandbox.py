"""`plugins.sandbox` — pure logic, no DB, no real plugin needed: a
deliberately slow/deliberately raising fake callable proves the wrapper's
behavior in isolation.
"""

from __future__ import annotations

import time

import pytest

from gov_platform.plugins.sandbox import PluginTimeoutError, run_sandboxed


def test_returns_the_wrapped_calls_result() -> None:
    assert run_sandboxed(lambda: 42) == 42


def test_reraises_the_wrapped_calls_exception_unchanged() -> None:
    def _raise() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_sandboxed(_raise)


def test_raises_plugin_timeout_error_when_the_budget_is_exceeded() -> None:
    def _slow() -> None:
        time.sleep(0.3)

    with pytest.raises(PluginTimeoutError):
        run_sandboxed(_slow, timeout_seconds=0.05)


def test_does_not_block_on_a_still_running_thread_after_timing_out() -> None:
    # Proves executor.shutdown(wait=False) actually doesn't block --
    # otherwise this test would take >=0.3s, not <0.2s.
    def _slow() -> None:
        time.sleep(0.3)

    started_at = time.monotonic()
    with pytest.raises(PluginTimeoutError):
        run_sandboxed(_slow, timeout_seconds=0.05)
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
