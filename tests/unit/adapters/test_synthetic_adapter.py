from __future__ import annotations

from gov_platform.adapters.synthetic import SyntheticAdapter, SyntheticSourcePayload


def test_translate_maps_every_field(synthetic_payload_json: dict[str, object]) -> None:
    payload = SyntheticSourcePayload(**synthetic_payload_json)  # type: ignore[arg-type]
    event = SyntheticAdapter().translate(payload)

    assert event.event_id == payload.source_event_id
    assert event.system_id == payload.source_system
    assert event.decision_type == payload.decision_type
    assert event.subject_ref == payload.subject_reference
    assert event.occurred_at == payload.occurred_at
    assert event.input_features == payload.features
    assert event.protected_attribute_refs == payload.protected_attributes
    assert event.decision_output == payload.decision


def test_translate_stamps_ingested_at_now(synthetic_payload_json: dict[str, object]) -> None:
    payload = SyntheticSourcePayload(**synthetic_payload_json)  # type: ignore[arg-type]
    event = SyntheticAdapter().translate(payload)

    assert event.ingested_at.tzinfo is not None
    assert event.ingested_at >= event.occurred_at
