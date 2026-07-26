"""Integration tests: the full vertical slice through real HTTP calls — no
mocking of the adapter, normalization, governance, or evidence layers.

M1 update: the successful-ingestion tests now need a real Postgres (see
conftest.requires_postgres) since EvidenceStore no longer has a SQLite
fallback. `healthz` and the malformed-input tests never reach persistence at
all and stay local-runnable, unchanged from M0. Successful-ingestion
assertions are relative (state-before + expected delta), not absolute
(`evidence_sequence_number == 1`) — this table is shared across the whole
CI run with no truncation between tests, same reasoning as
`test_evidence_store_postgres.py`. Every test also uses a unique
source_event_id, since `decision_events.id` is a hard primary key now.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import requires_postgres


def _unique_payload(base: dict[str, object]) -> dict[str, object]:
    payload = dict(base)
    payload["source_event_id"] = f"evt-{uuid4()}"
    return payload


def test_healthz_returns_200(api_client: TestClient) -> None:
    response = api_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "HEALTHY"}


@requires_postgres
def test_ingest_event_returns_allow_verdict_and_evidence_reference(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    store = api_client.app.state.evidence_store  # type: ignore[attr-defined]
    sequence_before = len(store.all())

    payload = _unique_payload(synthetic_payload_json)
    response = api_client.post("/v1/ingestion/events", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ALLOW"
    assert body["decision_event_id"] == payload["source_event_id"]
    assert body["evidence_sequence_number"] == sequence_before + 1
    assert len(body["evidence_record_hash"]) == 64


@requires_postgres
def test_ingest_event_writes_one_evidence_record_with_valid_chain(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    store = api_client.app.state.evidence_store  # type: ignore[attr-defined]
    tail_before = store.all()
    expected_previous_hash = tail_before[-1].record_hash if tail_before else "0" * 64

    payload = _unique_payload(synthetic_payload_json)
    response = api_client.post("/v1/ingestion/events", json=payload)
    body = response.json()

    records = store.all()
    new_record = records[-1]

    assert new_record.sequence_number == len(tail_before) + 1
    assert new_record.previous_hash == expected_previous_hash
    assert new_record.record_hash == body["evidence_record_hash"]
    assert new_record.payload["decision_event"]["event_id"] == payload["source_event_id"]


@requires_postgres
def test_two_ingested_events_chain_together(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    first_payload = _unique_payload(synthetic_payload_json)
    first = api_client.post("/v1/ingestion/events", json=first_payload)

    second_payload = _unique_payload(synthetic_payload_json)
    second = api_client.post("/v1/ingestion/events", json=second_payload)

    assert second.json()["evidence_sequence_number"] == first.json()["evidence_sequence_number"] + 1

    store = api_client.app.state.evidence_store  # type: ignore[attr-defined]
    records = store.all()
    first_id = first_payload["source_event_id"]
    second_id = second_payload["source_event_id"]
    first_record = next(r for r in records if r.decision_event_id == first_id)
    second_record = next(r for r in records if r.decision_event_id == second_id)
    assert second_record.previous_hash == first_record.record_hash


def test_malformed_payload_returns_422_not_500(api_client: TestClient) -> None:
    response = api_client.post("/v1/ingestion/events", json={"source_event_id": "only-one-field"})

    assert response.status_code == 422
    assert "internal server error" not in response.text.lower()


def test_empty_body_returns_422(api_client: TestClient) -> None:
    response = api_client.post("/v1/ingestion/events", json={})

    assert response.status_code == 422
