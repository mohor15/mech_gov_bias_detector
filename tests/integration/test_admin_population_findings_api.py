"""Population Findings Admin API — read-only, over real HTTP against a
real Postgres. CI-only (see conftest.requires_postgres). There is no
`POST` — a population finding is only ever produced by
`population_engine/run_policies.py`'s batch job, so tests seed one
directly through the repository, the same way `EvidenceStore`-produced
data is seeded for other read-only-API tests in this codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _seed_finding(db_engine, *, system_id: str | None = None) -> tuple[str, str]:
    """Returns (system_id, population_finding_id)."""
    with Session(db_engine) as session:
        if system_id is None:
            system_id = SystemRepository().create(session, name=f"finding-api-system-{uuid4()}").id
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system_id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
            outcome=PopulationFindingOutcome.FLAGGED,
            metric_values={"race:Black": 0.75},
            classification_snapshot={"race": "DIRECT"},
            rationale="test rationale",
            evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        PopulationFindingRepository().create(
            session, finding, signature="deadbeef", signing_key_id="default"
        )
        session.commit()
    return system_id, finding.population_finding_id


def test_get_a_seeded_finding_by_id(api_client: TestClient, db_engine) -> None:
    _system_id, finding_id = _seed_finding(db_engine)

    response = api_client.get(f"/v1/admin/population-findings/{finding_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == finding_id
    assert body["outcome"] == "FLAGGED"
    assert body["classification_snapshot"] == {"race": "DIRECT"}
    assert body["signature"] == "deadbeef"


def test_get_unknown_finding_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-findings/does-not-exist")

    assert response.status_code == 404


def test_list_includes_a_seeded_finding(api_client: TestClient, db_engine) -> None:
    _system_id, finding_id = _seed_finding(db_engine)

    response = api_client.get("/v1/admin/population-findings")

    assert response.status_code == 200
    assert finding_id in {f["id"] for f in response.json()}


def test_list_filtered_by_system_id_returns_only_that_systems_findings(
    api_client: TestClient, db_engine
) -> None:
    system_a, finding_a = _seed_finding(db_engine)
    _system_b, finding_b = _seed_finding(db_engine)

    response = api_client.get("/v1/admin/population-findings", params={"system_id": system_a})

    assert response.status_code == 200
    ids = {f["id"] for f in response.json()}
    assert finding_a in ids
    assert finding_b not in ids


def test_list_filtered_by_an_unbound_system_id_is_empty(api_client: TestClient) -> None:
    response = api_client.get(
        "/v1/admin/population-findings", params={"system_id": "no-such-system"}
    )

    assert response.status_code == 200
    assert response.json() == []
