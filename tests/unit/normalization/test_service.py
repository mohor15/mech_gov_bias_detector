from __future__ import annotations

from datetime import UTC, timedelta, timezone

from gov_platform.normalization.service import NormalizationService


def test_normalize_strips_whitespace(make_decision_event) -> None:
    event = make_decision_event(system_id="  synthetic-scorecard  ", subject_ref="  subject-001  ")
    normalized = NormalizationService().normalize(event)

    assert normalized.system_id == "synthetic-scorecard"
    assert normalized.subject_ref == "subject-001"


def test_normalize_rounds_feature_precision(make_decision_event) -> None:
    event = make_decision_event(input_features={"annual_income": 65000.123456})
    normalized = NormalizationService().normalize(event)

    assert normalized.input_features["annual_income"] == 65000.1235


def test_normalize_converts_timestamps_to_utc(make_decision_event) -> None:
    non_utc = timezone(timedelta(hours=5, minutes=30))
    event = make_decision_event(
        occurred_at=make_decision_event().occurred_at.astimezone(non_utc),
    )
    normalized = NormalizationService().normalize(event)

    assert normalized.occurred_at.tzinfo == UTC
    assert normalized.ingested_at.tzinfo == UTC


def test_normalize_does_not_mutate_input(make_decision_event) -> None:
    event = make_decision_event(system_id="  padded  ")
    NormalizationService().normalize(event)

    assert event.system_id == "  padded  "  # original untouched — DecisionEvent is frozen
