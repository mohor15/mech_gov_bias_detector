"""Protected Attribute Rules Admin API — over real HTTP against a real
Postgres. CI-only (see conftest.requires_postgres). Mirrors
`test_admin_systems_api.py`'s shape.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _unique_domain() -> str:
    return f"test-domain-{uuid4()}"


def test_create_a_direct_rule(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/protected-attribute-rules",
        json={"domain": _unique_domain(), "attribute_name": "race", "classification": "DIRECT"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["classification"] == "DIRECT"
    assert body["proxy_of"] is None


def test_create_a_proxy_rule(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/protected-attribute-rules",
        json={
            "domain": _unique_domain(),
            "attribute_name": "zip_code",
            "classification": "PROXY",
            "proxy_of": "race",
        },
    )

    assert response.status_code == 201
    assert response.json()["proxy_of"] == "race"


def test_create_a_proxy_rule_without_proxy_of_is_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/protected-attribute-rules",
        json={"domain": _unique_domain(), "attribute_name": "zip_code", "classification": "PROXY"},
    )

    assert response.status_code == 422


def test_create_a_duplicate_rule_is_409(api_client: TestClient) -> None:
    domain = _unique_domain()
    payload = {"domain": domain, "attribute_name": "race", "classification": "DIRECT"}
    first = api_client.post("/v1/admin/protected-attribute-rules", json=payload)
    assert first.status_code == 201

    second = api_client.post("/v1/admin/protected-attribute-rules", json=payload)
    assert second.status_code == 409


def test_list_protected_attribute_rules_includes_the_seeded_finance_ones(
    api_client: TestClient,
) -> None:
    response = api_client.get("/v1/admin/protected-attribute-rules")

    assert response.status_code == 200
    finance_attributes = {r["attribute_name"] for r in response.json() if r["domain"] == "FINANCE"}
    assert finance_attributes == {
        "race",
        "gender",
        "age",
        "marital_status",
        "zip_code",
        "first_name",
    }


def test_get_unknown_rule_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/protected-attribute-rules/does-not-exist")

    assert response.status_code == 404


def test_get_a_created_rule_by_id(api_client: TestClient) -> None:
    create_response = api_client.post(
        "/v1/admin/protected-attribute-rules",
        json={"domain": _unique_domain(), "attribute_name": "race", "classification": "DIRECT"},
    )
    rule_id = create_response.json()["id"]

    response = api_client.get(f"/v1/admin/protected-attribute-rules/{rule_id}")

    assert response.status_code == 200
    assert response.json()["id"] == rule_id
