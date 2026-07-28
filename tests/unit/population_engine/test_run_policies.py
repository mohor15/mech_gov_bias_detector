"""`population_engine.run_policies.default_window` — pure, no DB. The
DB-dependent parts of this module (`run_population_policy_binding`,
`main`) are covered by `tests/integration/test_population_run_policies_postgres.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gov_platform.population_engine.run_policies import default_window


def test_default_window_is_yesterdays_full_utc_day() -> None:
    as_of = datetime(2026, 7, 28, 15, 30, tzinfo=UTC)

    window_start, window_end = default_window(as_of)

    assert window_start == datetime(2026, 7, 27, tzinfo=UTC)
    assert window_end == datetime(2026, 7, 28, tzinfo=UTC)
    assert window_end - window_start == timedelta(days=1)


def test_default_window_ignores_the_time_of_day_component() -> None:
    early = default_window(datetime(2026, 7, 28, 0, 0, 1, tzinfo=UTC))
    late = default_window(datetime(2026, 7, 28, 23, 59, 59, tzinfo=UTC))

    assert early == late


def test_default_window_defaults_to_now_when_as_of_is_omitted() -> None:
    window_start, window_end = default_window()

    assert window_end - window_start == timedelta(days=1)
    assert window_end.tzinfo is UTC
