"""`reporting.compliance_report`'s model shape — no DB. `get_compliance_report`
itself executes real SQL against `verdicts`/`findings`/`population_findings`/
`verdict_reviews`/`population_finding_reviews` and is exercised only against
a real Postgres instance, in `tests/integration/test_compliance_report_postgres.py`
— this project's models are never used to generate DDL against any other
dialect (see `db/models.py`'s own module docstring), so there is no SQLite
stand-in for it here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.audit.hash_chain import canonical_json
from gov_platform.reporting.compliance_report import (
    ComplianceReport,
    FindingCounts,
    PopulationFindingCounts,
    ReviewOutcomeCounts,
    VerdictCounts,
)


def _make_report(**overrides: object) -> ComplianceReport:
    defaults: dict[str, object] = {
        "window_start": datetime(2026, 6, 1, tzinfo=UTC),
        "window_end": datetime(2026, 7, 1, tzinfo=UTC),
        "system_id": None,
        "verdicts": VerdictCounts(by_status={"ALLOW": 3}),
        "findings": FindingCounts(by_policy={"always-allow": {"CLEAR": 3}}),
        "population_findings": PopulationFindingCounts(by_policy={}),
        "reviews": ReviewOutcomeCounts(
            verdict_reviews_by_resolution={},
            population_finding_reviews_by_resolution={},
        ),
        "generated_at": datetime(2026, 7, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ComplianceReport(**defaults)  # type: ignore[arg-type]


def test_compliance_report_is_frozen() -> None:
    report = _make_report()

    with pytest.raises(ValidationError):
        report.system_id = "some-system"  # type: ignore[misc]


def test_no_system_id_means_platform_wide() -> None:
    report = _make_report(system_id=None)

    assert report.system_id is None


def test_review_outcome_counts_holds_two_independent_dicts() -> None:
    reviews = ReviewOutcomeCounts(
        verdict_reviews_by_resolution={"CONFIRMED": 2, "DISMISSED": 1},
        population_finding_reviews_by_resolution={"CONFIRMED": 5},
    )

    assert reviews.verdict_reviews_by_resolution == {"CONFIRMED": 2, "DISMISSED": 1}
    assert reviews.population_finding_reviews_by_resolution == {"CONFIRMED": 5}


def test_model_dump_json_mode_serializes_datetimes_as_iso_strings() -> None:
    report = _make_report()

    dumped = report.model_dump(mode="json")

    assert dumped["window_start"] == "2026-06-01T00:00:00Z"
    assert dumped["window_end"] == "2026-07-01T00:00:00Z"
    assert dumped["generated_at"] == "2026-07-30T00:00:00Z"


def test_model_dump_json_mode_is_canonical_json_serializable_and_deterministic() -> None:
    report = _make_report()

    first = canonical_json(report.model_dump(mode="json"))
    second = canonical_json(report.model_dump(mode="json"))

    assert first == second
    # sort_keys=True -- confirms this report's own JSON export reuses
    # audit/hash_chain.canonical_json's determinism guarantee, not just a
    # plain json.dumps call.
    assert '"findings"' in first
    assert first.index('"findings"') < first.index('"generated_at"')
    assert first.index('"generated_at"') < first.index('"population_findings"')


def test_finding_counts_nests_policy_id_then_outcome() -> None:
    findings = FindingCounts(by_policy={"direct-attribute-in-inputs": {"CLEAR": 2, "FLAGGED": 1}})

    assert findings.by_policy["direct-attribute-in-inputs"] == {"CLEAR": 2, "FLAGGED": 1}
