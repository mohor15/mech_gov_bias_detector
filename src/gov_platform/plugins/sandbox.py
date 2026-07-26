"""Plugin execution sandbox — architecture §6, M3.

Timeout + exception isolation only — deliberately **not** process- or
container-level isolation. There is no untrusted third-party plugin
author yet (every `Adapter`/`Policy` in this codebase is first-party code
reviewed the same way any other module is); building real OS-level
isolation now would be solving a threat model that doesn't exist yet. See
`docs/milestones/M3.md` §13.1 for the full reasoning — this is the single
biggest scope-narrowing call in the M3 design and is documented here
precisely so nothing downstream mistakes this for stronger isolation than
it actually provides.

Exception isolation needs no special handling here: `Future.result()`
already re-raises whatever the wrapped call raised, unchanged, so a
plugin's own exceptions (e.g. `ProtectedAttributeResolver`'s `ValueError`)
reach the caller exactly as they would without this wrapper, and existing
exception handling (see `api/app.py`) keeps working. What this module
actually adds is the timeout.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TypeVar

_T = TypeVar("_T")

DEFAULT_TIMEOUT_SECONDS = 5.0


class PluginTimeoutError(Exception):
    """A plugin call exceeded its execution time budget.

    Soft timeout only: Python cannot safely force-terminate a running
    thread, so the underlying call keeps running in the background until
    it finishes or raises on its own — this function simply stops waiting
    for it and discards whatever result eventually arrives. This is the
    honest limit of "exception isolation without process/container
    isolation" (see this module's docstring); a plugin that hangs forever
    still consumes a background thread forever, it just no longer blocks
    the caller.
    """


def run_sandboxed(fn: Callable[[], _T], *, timeout_seconds: float | None = None) -> _T:
    """Run zero-argument callable `fn` under a time budget.

    Callers wrap a plugin call as a zero-argument closure, e.g.
    ``run_sandboxed(lambda: adapter.translate(payload))``. Re-raises
    whatever `fn` raises, unchanged; raises `PluginTimeoutError` instead
    if `fn` doesn't complete within `timeout_seconds`.

    `timeout_seconds` defaults to `None`, resolved to `DEFAULT_TIMEOUT_SECONDS`
    *inside* this function rather than as a parameter default — callers
    that don't pass it explicitly (every ingestion-route call site today)
    pick up changes to the module-level constant at call time, which is
    what lets a test lower it via `monkeypatch.setattr` without needing a
    real multi-second sleep to prove the timeout path end to end.
    """
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        raise PluginTimeoutError(
            f"plugin call exceeded its {timeout_seconds}s execution budget"
        ) from exc
    finally:
        # wait=False: do not block returning to the caller on a thread
        # that may never finish -- see PluginTimeoutError's docstring.
        executor.shutdown(wait=False)
