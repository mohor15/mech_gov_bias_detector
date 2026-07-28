from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome


def _finding(**overrides: object) -> PopulationFinding:
    defaults: dict[str, object] = {
        "population_finding_id": "pf-001",
        "population_policy_id": "adverse-impact-ratio",
        "population_policy_version": "0.1.0",
        "system_id": "sys-001",
        "window_start": datetime(2026, 1, 1, tzinfo=UTC),
        "window_end": datetime(2026, 1, 2, tzinfo=UTC),
        "outcome": PopulationFindingOutcome.CLEAR,
        "metric_values": {},
        "classification_snapshot": {},
        "rationale": "test rationale",
        "evaluated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PopulationFinding(**defaults)  # type: ignore[arg-type]


def test_valid_population_finding_constructs() -> None:
    finding = _finding()
    assert finding.outcome is PopulationFindingOutcome.CLEAR


def test_population_finding_carries_no_decision_event_id() -> None:
    """The entire reason this is a new type, not a reuse of Finding --
    see schemas/population_finding.py's module docstring."""
    assert "decision_event_id" not in PopulationFinding.model_fields


def test_population_finding_is_frozen() -> None:
    finding = _finding()
    with pytest.raises(ValidationError):
        finding.outcome = PopulationFindingOutcome.FLAGGED  # type: ignore[misc]


def test_classification_snapshot_round_trips() -> None:
    finding = _finding(classification_snapshot={"race": "DIRECT", "gender": "DIRECT"})
    assert finding.classification_snapshot == {"race": "DIRECT", "gender": "DIRECT"}
