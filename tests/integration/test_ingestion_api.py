"""Integration tests: the full M0 vertical slice through real HTTP calls
against a real (temp-file) SQLite-backed app instance — no mocking of the
adapter, normalization, governance, or evidence layers. This is the
milestone's core acceptance criterion, exercised end to end.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gov_platform.audit.evidence_store import GENESIS_HASH


def test_healthz_returns_200(api_client: TestClient) -> None:
    response = api_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "HEALTHY"}


def test_ingest_event_returns_allow_verdict_and_evidence_reference(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    response = api_client.post("/v1/ingestion/events", json=synthetic_payload_json)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ALLOW"
    assert body["decision_event_id"] == synthetic_payload_json["source_event_id"]
    assert body["evidence_sequence_number"] == 1
    assert len(body["evidence_record_hash"]) == 64


def test_ingest_event_writes_one_evidence_record_with_valid_chain(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    response = api_client.post("/v1/ingestion/events", json=synthetic_payload_json)
    body = response.json()

    store = api_client.app.state.evidence_store  # type: ignore[attr-defined]
    records = store.all()

    assert len(records) == 1
    assert records[0].sequence_number == 1
    assert records[0].previous_hash == GENESIS_HASH
    assert records[0].record_hash == body["evidence_record_hash"]
    stored_event_id = records[0].payload["decision_event"]["event_id"]
    assert stored_event_id == synthetic_payload_json["source_event_id"]


def test_two_ingested_events_chain_together(
    api_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    first = api_client.post("/v1/ingestion/events", json=synthetic_payload_json)

    second_payload = dict(synthetic_payload_json)
    second_payload["source_event_id"] = "src-evt-002"
    second = api_client.post("/v1/ingestion/events", json=second_payload)

    assert first.json()["evidence_sequence_number"] == 1
    assert second.json()["evidence_sequence_number"] == 2

    store = api_client.app.state.evidence_store  # type: ignore[attr-defined]
    records = store.all()
    assert records[1].previous_hash == records[0].record_hash


def test_malformed_payload_returns_422_not_500(api_client: TestClient) -> None:
    response = api_client.post("/v1/ingestion/events", json={"source_event_id": "only-one-field"})

    assert response.status_code == 422
    assert "internal server error" not in response.text.lower()


def test_empty_body_returns_422(api_client: TestClient) -> None:
    response = api_client.post("/v1/ingestion/events", json={})

    assert response.status_code == 422
