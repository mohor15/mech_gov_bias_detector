"""Admin API — System registration, over real HTTP against a real Postgres.
CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import requires_postgres

pytestmark = requires_postgres


def test_register_system_returns_201_with_generated_id(api_client: TestClient) -> None:
    payload = {
        "name": f"scorecard-{uuid4()}",
        "domain": "FINANCE",
        "risk_tier": "HIGH",
        "owner": "risk-team",
    }
    response = api_client.post("/v1/admin/systems", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["domain"] == "FINANCE"
    assert body["risk_tier"] == "HIGH"
    assert body["owner"] == "risk-team"
    assert len(body["id"]) > 0


def test_register_system_with_only_required_fields(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/systems", json={"name": f"minimal-{uuid4()}"})

    assert response.status_code == 201
    body = response.json()
    assert body["domain"] is None
    assert body["risk_tier"] is None
    assert body["owner"] is None


def test_registering_the_same_name_twice_is_a_conflict(api_client: TestClient) -> None:
    name = f"dup-{uuid4()}"
    first = api_client.post("/v1/admin/systems", json={"name": name})
    second = api_client.post("/v1/admin/systems", json={"name": name})

    assert first.status_code == 201
    assert second.status_code == 409


def test_get_system_by_id(api_client: TestClient) -> None:
    created = api_client.post("/v1/admin/systems", json={"name": f"lookup-{uuid4()}"}).json()

    response = api_client.get(f"/v1/admin/systems/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_unknown_system_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/systems/does-not-exist")
    assert response.status_code == 404


def test_list_systems_includes_a_freshly_registered_one(api_client: TestClient) -> None:
    name = f"listed-{uuid4()}"
    api_client.post("/v1/admin/systems", json={"name": name})

    response = api_client.get("/v1/admin/systems")

    assert response.status_code == 200
    names = {system["name"] for system in response.json()}
    assert name in names


def test_ingestion_reuses_a_pre_registered_system(
    api_client: TestClient, synthetic_payload_json
) -> None:
    name = f"pre-registered-{uuid4()}"
    registered = api_client.post("/v1/admin/systems", json={"name": name}).json()

    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"
    payload["source_system"] = name
    ingest_response = api_client.post("/v1/ingestion/events/synthetic", json=payload)
    assert ingest_response.status_code == 201

    systems_after = api_client.get("/v1/admin/systems").json()
    matching = [s for s in systems_after if s["name"] == name]

    # Exactly one System row for this name — ingestion linked to the
    # pre-registered row rather than creating a duplicate.
    assert len(matching) == 1
    assert matching[0]["id"] == registered["id"]
