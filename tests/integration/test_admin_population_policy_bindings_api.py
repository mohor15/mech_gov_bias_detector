"""Population Policy Bindings Admin API — over real HTTP against a real
Postgres. CI-only (see conftest.requires_postgres). Mirrors
`test_admin_policy_bindings_api.py`'s shape.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response
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


# --- M8: admin-configurable parameters and the relaxed uniqueness
# constraint (docs/milestones/M8.md §4.3/§4.4) ---


def test_create_with_parameters_persists_and_returns_them(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)
    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={
            "system_id": system_id,
            "population_policy_id": "adverse-impact-ratio",
            "parameters": {"threshold": 0.75},
        },
    )

    assert response.status_code == 201
    assert response.json()["parameters"] == {"threshold": 0.75}


def test_create_with_no_parameters_defaults_to_an_empty_dict(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)
    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )

    assert response.status_code == 201
    assert response.json()["parameters"] == {}


def test_recreating_a_binding_after_deactivation_succeeds_through_the_api(
    api_client: TestClient, db_engine
) -> None:
    """The end-to-end proof for the headline hostile-review-pass fix
    (docs/milestones/M8.md §4.4/§13.19): this exact sequence is what the
    pre-M8 schema *and* the pre-fix conflict check both blocked. Goes
    through the HTTP layer deliberately, not the repository directly --
    the original bug lived entirely in this endpoint's own conflict
    check, not in the repository or the schema alone."""
    system_id = _new_system_id(db_engine)
    payload = {"system_id": system_id, "population_policy_id": "adverse-impact-ratio"}

    first = api_client.post("/v1/admin/population-policy-bindings", json=payload)
    assert first.status_code == 201
    binding_id = first.json()["id"]

    deactivate = api_client.post(f"/v1/admin/population-policy-bindings/{binding_id}/deactivate")
    assert deactivate.status_code == 200

    second = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={**payload, "parameters": {"threshold": 0.7}},
    )

    assert second.status_code == 201
    assert second.json()["id"] != binding_id
    assert second.json()["parameters"] == {"threshold": 0.7}
    assert second.json()["lifecycle_state"] == "ACTIVE"


def test_recreating_a_still_active_binding_is_still_409(api_client: TestClient, db_engine) -> None:
    """The conflict check must not become permissive across the board --
    only across `lifecycle_state`: a still-`ACTIVE` binding still blocks
    a duplicate, exactly as before M8."""
    system_id = _new_system_id(db_engine)
    payload = {"system_id": system_id, "population_policy_id": "adverse-impact-ratio"}

    first = api_client.post("/v1/admin/population-policy-bindings", json=payload)
    assert first.status_code == 201

    second = api_client.post("/v1/admin/population-policy-bindings", json=payload)

    assert second.status_code == 409


def test_deactivating_an_unknown_binding_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/population-policy-bindings/does-not-exist/deactivate")

    assert response.status_code == 404


def test_activating_an_already_active_binding_is_409(api_client: TestClient, db_engine) -> None:
    """M14 §12.1 option (a): a redundant `activate` is a conflict, never a
    silent 200 no-op -- a newly-created binding is already `ACTIVE`
    (`docs/milestones/M14.md` §5.2/§12.1/§12.2)."""
    system_id = _new_system_id(db_engine)
    create_response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )
    binding_id = create_response.json()["id"]

    response = api_client.post(f"/v1/admin/population-policy-bindings/{binding_id}/activate")

    assert response.status_code == 409


def test_deactivating_an_already_inactive_binding_is_409(api_client: TestClient, db_engine) -> None:
    """M14 §12.1 option (a): a redundant `deactivate` is a conflict, never
    a silent 200 no-op."""
    system_id = _new_system_id(db_engine)
    create_response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={"system_id": system_id, "population_policy_id": "adverse-impact-ratio"},
    )
    binding_id = create_response.json()["id"]
    first_deactivate = api_client.post(
        f"/v1/admin/population-policy-bindings/{binding_id}/deactivate"
    )
    assert first_deactivate.status_code == 200

    response = api_client.post(f"/v1/admin/population-policy-bindings/{binding_id}/deactivate")

    assert response.status_code == 409


# --- post-freeze addendum: reject non-finite (NaN/Infinity) parameter
# values at binding-creation time (docs/milestones/M8.md's Production-
# Readiness Review addendum) ---


def _post_raw(api_client: TestClient, system_id: str, raw_threshold_literal: str) -> Response:
    """`api_client.post(..., json=...)` refuses to encode NaN/Infinity
    client-side (httpx's own `json=` convenience wrapper calls stdlib
    `json.dumps` with its default, strict settings) -- sending the raw
    bytes directly is the only way to actually exercise what the *server*
    does with a non-standard-but-technically-parseable JSON literal in
    the request body, bypassing the client library's own guard."""
    raw_body = (
        f'{{"system_id": "{system_id}", "population_policy_id": "adverse-impact-ratio", '
        f'"parameters": {{"threshold": {raw_threshold_literal}}}}}'
    )
    return api_client.post(
        "/v1/admin/population-policy-bindings",
        content=raw_body.encode(),
        headers={"content-type": "application/json"},
    )


def test_a_nan_parameter_value_is_rejected_with_a_clear_422(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)

    response = _post_raw(api_client, system_id, "NaN")

    assert response.status_code == 422
    assert "finite number" in response.json()["detail"]
    assert "threshold" in response.json()["detail"]


def test_an_infinity_parameter_value_is_rejected_with_a_clear_422(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)

    response = _post_raw(api_client, system_id, "Infinity")

    assert response.status_code == 422
    assert "finite number" in response.json()["detail"]


def test_a_negative_infinity_parameter_value_is_rejected_with_a_clear_422(
    api_client: TestClient, db_engine
) -> None:
    system_id = _new_system_id(db_engine)

    response = _post_raw(api_client, system_id, "-Infinity")

    assert response.status_code == 422
    assert "finite number" in response.json()["detail"]


def test_a_rejected_non_finite_value_is_never_persisted(api_client: TestClient, db_engine) -> None:
    system_id = _new_system_id(db_engine)

    rejected = _post_raw(api_client, system_id, "NaN")
    assert rejected.status_code == 422

    listing = api_client.get("/v1/admin/population-policy-bindings")
    matching = [b for b in listing.json() if b["system_id"] == system_id]

    assert matching == []


def test_a_finite_parameter_value_is_still_accepted(api_client: TestClient, db_engine) -> None:
    """The finite-value check must not become overly broad -- an
    ordinary, valid override still works exactly as before."""
    system_id = _new_system_id(db_engine)

    response = api_client.post(
        "/v1/admin/population-policy-bindings",
        json={
            "system_id": system_id,
            "population_policy_id": "adverse-impact-ratio",
            "parameters": {"threshold": 0.75},
        },
    )

    assert response.status_code == 201
    assert response.json()["parameters"] == {"threshold": 0.75}
