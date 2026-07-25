from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.finding import Finding, FindingOutcome


def _finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "finding_id": "find-001",
        "decision_event_id": "evt-001",
        "policy_id": "always-allow",
        "policy_version": "0.1.0",
        "outcome": FindingOutcome.CLEAR,
        "confidence": 1.0,
        "rationale": "test rationale",
        "metric_values": {},
        "evaluated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def test_valid_finding_constructs() -> None:
    finding = _finding()
    assert finding.outcome is FindingOutcome.CLEAR


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_out_of_range_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _finding(confidence=confidence)


def test_finding_is_frozen() -> None:
    finding = _finding()
    with pytest.raises(ValidationError):
        finding.outcome = FindingOutcome.FLAGGED  # type: ignore[misc]
