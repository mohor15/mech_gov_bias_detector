from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.decision_event import DecisionEvent


def test_valid_decision_event_constructs(make_decision_event) -> None:
    event = make_decision_event()
    assert event.event_id == "evt-001"
    assert event.input_features["annual_income"] == 65000.0


@pytest.mark.parametrize("missing_field", ["event_id", "system_id", "decision_type", "subject_ref"])
def test_missing_required_field_rejected(make_decision_event, missing_field: str) -> None:
    event = make_decision_event()
    payload = event.model_dump(mode="json")
    del payload[missing_field]

    with pytest.raises(ValidationError):
        DecisionEvent(**payload)


def test_empty_required_string_rejected(make_decision_event) -> None:
    with pytest.raises(ValidationError):
        make_decision_event(event_id="")


def test_naive_timestamp_rejected(make_decision_event) -> None:
    with pytest.raises(ValidationError):
        make_decision_event(occurred_at=datetime(2026, 1, 1))  # noqa: DTZ001 — deliberately naive, testing rejection


def test_decision_event_is_frozen(make_decision_event) -> None:
    event = make_decision_event()
    with pytest.raises(ValidationError):
        event.event_id = "mutated"  # type: ignore[misc]
