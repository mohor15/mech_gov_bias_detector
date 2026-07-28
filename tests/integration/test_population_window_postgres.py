"""`population_engine.window.build_population_window` — the "Event Lake"
read path, against a real Postgres. CI-only (see conftest.requires_postgres).

Exercises the actual SQL (the `protected_attribute_refs::jsonb`/
`decision_output::jsonb` casts over what is, on disk, plain TEXT — see
that module's docstring) rather than trusting it looks right, per this
project's own "verified against real Postgres" discipline established at
M1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gov_platform.population_engine.window import build_population_window
from tests.conftest import requires_postgres

pytestmark = requires_postgres

_IN_WINDOW = datetime(2026, 2, 1, 12, tzinfo=UTC)
_WINDOW_START = datetime(2026, 2, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 2, 2, tzinfo=UTC)
_BEFORE_WINDOW = _WINDOW_START - timedelta(days=1)


def test_groups_and_counts_by_direct_attribute_value(db_engine, seed_finance_decisions) -> None:
    system_id = seed_finance_decisions(
        [
            ({"race": "Black"}, True, _IN_WINDOW),
            ({"race": "Black"}, False, _IN_WINDOW),
            ({"race": "White"}, True, _IN_WINDOW),
        ]
    )

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    by_value = {g.attribute_value: g for g in window.group_counts if g.attribute_name == "race"}
    assert by_value["Black"].total_count == 2
    assert by_value["Black"].favorable_outcome_count == 1
    assert by_value["White"].total_count == 1
    assert by_value["White"].favorable_outcome_count == 1


def test_classification_snapshot_reflects_the_domains_direct_rules(
    db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    # FINANCE's DIRECT rules, seeded by conftest._seed_plugin_registry --
    # see protected_attributes/classification.py's FINANCE ruleset.
    assert window.classification_snapshot == {
        "age": "DIRECT",
        "gender": "DIRECT",
        "marital_status": "DIRECT",
        "race": "DIRECT",
    }


def test_events_outside_the_window_are_excluded(db_engine, seed_finance_decisions) -> None:
    system_id = seed_finance_decisions(
        [
            ({"race": "Black"}, True, _BEFORE_WINDOW),
            ({"race": "Black"}, True, _IN_WINDOW),
        ]
    )

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    black = next(g for g in window.group_counts if g.attribute_value == "Black")
    assert black.total_count == 1


def test_window_end_is_exclusive(db_engine, seed_finance_decisions) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _WINDOW_END)])

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    assert window.group_counts == []


def test_a_system_with_no_decisions_in_range_is_an_empty_window_not_an_error(
    db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([])

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    assert window.group_counts == []
    assert window.classification_snapshot == {
        "age": "DIRECT",
        "gender": "DIRECT",
        "marital_status": "DIRECT",
        "race": "DIRECT",
    }


def test_a_system_with_no_registered_domain_produces_an_empty_window(
    db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions(
        [({"country": "India"}, True, _IN_WINDOW)], domain=None
    )

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    assert window.group_counts == []
    assert window.classification_snapshot == {}


def test_an_attribute_a_decision_did_not_supply_produces_no_group_for_it(
    db_engine, seed_finance_decisions
) -> None:
    # This event supplies only "race" -- "gender"/"age"/"marital_status"
    # are DIRECT for FINANCE but weren't supplied, and must not appear as
    # a spurious group (e.g. keyed on a JSON null).
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])

    window = build_population_window(
        db_engine, system_id=system_id, window_start=_WINDOW_START, window_end=_WINDOW_END
    )

    assert {g.attribute_name for g in window.group_counts} == {"race"}


def test_raises_for_an_unknown_system_id(db_engine) -> None:
    with pytest.raises(ValueError, match="no system"):
        build_population_window(
            db_engine,
            system_id="no-such-system",
            window_start=_WINDOW_START,
            window_end=_WINDOW_END,
        )
