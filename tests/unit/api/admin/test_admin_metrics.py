"""`api.admin.metrics.resolve_since` — pure, DB-free. The endpoint itself
(`GET /v1/admin/metrics`) is covered in
`tests/integration/test_admin_metrics_api.py` — see
`docs/milestones/M7.md` §10.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gov_platform.api.admin.metrics import resolve_since


def test_none_defaults_to_the_last_24_hours() -> None:
    before = datetime.now(UTC)
    resolved = resolve_since(None)
    after = datetime.now(UTC)

    assert before - timedelta(hours=24) <= resolved <= after - timedelta(hours=24)


def test_a_timezone_aware_value_is_returned_unchanged() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)

    assert resolve_since(since) == since


def test_a_naive_value_raises_value_error() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_since(datetime(2026, 1, 1))
