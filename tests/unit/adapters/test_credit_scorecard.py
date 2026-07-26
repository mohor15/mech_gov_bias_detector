from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.adapters.credit_scorecard import CreditScorecardAdapter, CreditScorecardPayload


def _payload(**overrides: object) -> CreditScorecardPayload:
    defaults: dict[str, object] = {
        "decision_id": "score-001",
        "applicant_id": "applicant-001",
        "system_name": "acme-scorecard",
        "scored_at": datetime(2026, 1, 1, tzinfo=UTC),
        "feature_vector": {"annual_income": 65000.0, "debt_to_income": 0.3},
        "demographic_indicators": {"race": "Black", "zip_code": "12345"},
        "model_score": 712.5,
        "decision_threshold": 650.0,
        "approved": True,
        "reason_codes": ["R01"],
    }
    defaults.update(overrides)
    return CreditScorecardPayload(**defaults)  # type: ignore[arg-type]


def test_translate_maps_identity_and_timing_fields() -> None:
    payload = _payload()
    event = CreditScorecardAdapter().translate(payload)

    assert event.event_id == payload.decision_id
    assert event.system_id == payload.system_name
    assert event.subject_ref == payload.applicant_id
    assert event.occurred_at == payload.scored_at
    assert event.decision_type == "credit_decision"


def test_translate_maps_features_and_protected_attributes_separately() -> None:
    payload = _payload()
    event = CreditScorecardAdapter().translate(payload)

    assert event.input_features == payload.feature_vector
    assert event.protected_attribute_refs == payload.demographic_indicators
    # The two must stay disjoint concepts at the translation boundary --
    # DirectAttributeInInputsPolicy depends on that separation existing to
    # have something meaningful to check.
    assert not set(event.input_features) & set(event.protected_attribute_refs)


def test_translate_folds_scoring_details_into_decision_output() -> None:
    payload = _payload()
    event = CreditScorecardAdapter().translate(payload)

    assert event.decision_output == {
        "approved": True,
        "model_score": 712.5,
        "decision_threshold": 650.0,
        "reason_codes": ["R01"],
    }


def test_translate_stamps_ingested_at_now() -> None:
    payload = _payload()
    event = CreditScorecardAdapter().translate(payload)

    assert event.ingested_at.tzinfo is not None
    assert event.ingested_at >= event.occurred_at


def test_translate_handles_a_direct_attribute_leaking_into_the_feature_vector() -> None:
    # Not a realistic well-formed payload, but a real adapter must
    # translate it faithfully regardless -- detecting the leak is the
    # policy's job (see test_direct_attribute_in_inputs.py), not the
    # adapter's.
    payload = _payload(feature_vector={"race": 1.0, "annual_income": 65000.0})
    event = CreditScorecardAdapter().translate(payload)

    assert event.input_features == {"race": 1.0, "annual_income": 65000.0}
