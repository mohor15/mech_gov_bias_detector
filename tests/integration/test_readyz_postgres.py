"""`GET /readyz` — real Postgres round trip, including a real negative
case (the database genuinely unreachable), not just the happy path. CI-only
(see conftest.requires_postgres). Mirrors `test_privilege_enforcement.py`'s
own discipline of proving the failure mode, not just asserting success.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gov_platform.api.app import create_app
from gov_platform.config.settings import Settings
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def test_readyz_returns_200_when_the_database_is_reachable(api_client: TestClient) -> None:
    response = api_client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "READY"}


def test_readyz_returns_503_when_the_database_is_unreachable() -> None:
    # A real connection failure, not a mock -- a bad port on localhost,
    # per docs/milestones/M7.md §12/db/session.py's own bounded
    # connect_timeout (found necessary during this milestone's own
    # implementation: an unreachable host can otherwise hang for the OS's
    # full TCP-retransmission timeout, well past a minute).
    unreachable_settings = Settings(
        DATABASE_URL="postgresql+psycopg://baduser:badpass@localhost:59999/nope"
    )
    client = TestClient(create_app(settings=unreachable_settings))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unreachable"}
