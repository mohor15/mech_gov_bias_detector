"""Population Policy Bindings Admin API — over real HTTP against a real
Postgres. CI-only (see conftest.requires_postgres). Mirrors
`test_admin_policy_bindings_api.py`'s shape.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.db.repositories.system import SystemRepository
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _new_system_id(db_engine) -> str:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"admin-api-system-{uuid4()}")
        session.commit()
    return system.id


def test_create_a_binding_for_a_known_system_and_population_policy_succeeds(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)
    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["system_id"] == system_id
    assert body["population_policy_id"] == "adverse-impact-ratio"
    assert body["lifecycle_state"] == "ACTIVE"


def test_create_a_duplicate_binding_is_409(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)
    payload = {"system_id": system_id, "population_policy_id": "adverse-impact-ratio"}
    first = api_client.post("/v1/admin/population-policy-bindings", json=payload)
    assert first.status_code == 201

    second = api_client.post("/v1/admin/population-policy-bindings", json=payload)
    assert second.status_code == 409


def test_create_with_unknown_system_id_is_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": "no-such-system", "population_policy_id": "adverse-impact-ratio"},
    )

    assert response.status_code == 422
    assert "system" in response.json()["detail"]


def test_create_with_unknown_population_policy_id_is_422(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)
    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "no-such-population-policy"},
    )

    assert response.status_code == 422
    assert "population_policy_id" in response.json()["detail"]


def test_get_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-policy-bindings/does-not-exist")

    assert response.status_code == 404


def test_get_a_created_binding_by_id(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)
    create_response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )
    binding_id = create_response.json()["id"]

    response = api_client.get(f"/v1/admin/population-policy-bindings/{binding_id}")

    assert response.status_code == 200
    assert response.json()["id"] == binding_id


def test_list_includes_a_created_binding(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)
    api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )

    response = api_client.get("/v1/admin/population-policy-bindings")

    assert response.status_code == 200
    pairs = {(b["system_id"], b["population_policy_id"]) for b in response.json()}
    assert (system_id, "adverse-impact-ratio") in pairs


def test_deactivating_and_reactivating_a_binding(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)
    create_response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )
    binding_id = create_response.json()["id"]

    deactivate_response = api_client.post(
        f"/v1/admin/population-policy-bindings/{binding_id}/deactivate"
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["lifecycle_state"] == "INACTIVE"

    activate_response = api_client.post(
        f"/v1/admin/population-policy-bindings/{binding_id}/activate"
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["lifecycle_state"] == "ACTIVE"


def test_activating_an_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/population-policy-bindings/does-not-exist/activate")

    assert response.status_code == 404


def test_deactivating_an_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/population-policy-bindings/does-not-exist/deactivate")

    assert response.status_code == 404
