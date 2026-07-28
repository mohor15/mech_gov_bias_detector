"""Metrics Admin API — over real HTTP against a real Postgres. CI-only
(see conftest.requires_postgres). The underlying aggregate queries are
covered in depth by `tests/integration/test_metrics_postgres.py`; this
file covers the HTTP-layer contract (`since` parsing, defaulting,
response shape).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import requires_postgres

pytestmark = requires_postgres


def test_get_metrics_with_no_since_defaults_to_the_last_24_hours(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/metrics")

    assert response.status_code == 200
    body = response.json()
    window_start = datetime.fromisoformat(body["governance"]["window_start"])
    window_end = datetime.fromisoformat(body["governance"]["window_end"])
    assert window_end - window_start <= timedelta(hours=24, minutes=1)
    assert window_end - window_start >= timedelta(hours=23, minutes=59)


def test_get_metrics_with_an_explicit_since_uses_it(api_client: TestClient) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)

    response = api_client.get("/v1/admin/metrics", params={"since": since.isoformat()})

    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["governance"]["window_start"]) == since


def test_get_metrics_with_a_naive_since_is_422(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/metrics", params={"since": "2026-01-01T00:00:00"})

    assert response.status_code == 422
    assert "timezone-aware" in response.json()["detail"]


def test_response_shape_has_both_system_and_governance_sections(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/metrics")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"system", "governance", "computed_at"}
    assert set(body["system"]) == {
        "db_reachable",
        "db_latency_ms",
        "evidence_chain_latest_sequence_number",
        "plugin_counts",
        "population_binding_staleness",
    }
    assert set(body["governance"]) == {
        "window_start",
        "window_end",
        "verdict_counts_by_status",
        "finding_counts_by_policy",
        "population_finding_counts_by_policy",
        "shadow_disagreement_rate_by_policy",
    }
