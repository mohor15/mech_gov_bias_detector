"""Tests for `MaxBodySizeMiddleware` — added during the M0 finalization
review alongside the middleware itself, closing a request-body-size gap
that was previously both unfixed and untested.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from gov_platform.api.app import create_app
from gov_platform.config.settings import Settings
from tests.conftest import requires_postgres


def test_oversized_body_is_rejected_with_413(
    test_settings: Settings, synthetic_payload_json: dict[str, Any]
) -> None:
    tiny_limit_settings = test_settings.model_copy(update={"MAX_REQUEST_BODY_BYTES": 10})
    app = create_app(settings=tiny_limit_settings)
    client = TestClient(app)

    response = client.post("/v1/ingestion/events", json=synthetic_payload_json)

    assert response.status_code == 413
    assert "byte limit" in response.json()["detail"]


@requires_postgres
def test_body_within_limit_is_not_rejected_by_the_middleware(
    test_settings: Settings, synthetic_payload_json: dict[str, Any]
) -> None:
    # Default limit (1MB) is generous for this payload — the middleware must
    # not interfere with the normal, in-scope request path. Needs Postgres:
    # unlike the 413 case (rejected before the route runs at all), proving
    # a request is genuinely *let through* means it must succeed end to end.
    app = create_app(settings=test_settings)
    client = TestClient(app)

    response = client.post("/v1/ingestion/events", json=synthetic_payload_json)

    assert response.status_code != 413
    assert response.status_code == 201


def test_healthz_is_unaffected_by_the_body_size_limit(test_settings: Settings) -> None:
    tiny_limit_settings = test_settings.model_copy(update={"MAX_REQUEST_BODY_BYTES": 1})
    app = create_app(settings=tiny_limit_settings)
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200


def test_non_http_scopes_pass_through_untouched(test_settings: Settings) -> None:
    # Lifespan (startup/shutdown) events are a non-"http" ASGI scope every
    # real deployment sends; the middleware must pass them straight through
    # rather than only having been exercised against HTTP requests.
    app = create_app(settings=test_settings)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
