"""Population Findings Admin API — read-only, over real HTTP against a
real Postgres. CI-only (see conftest.requires_postgres). There is no
`POST` — a population finding is only ever produced by
`population_engine/run_policies.py`'s batch job, so tests seed one
directly through the repository, the same way `EvidenceStore`-produced
data is seeded for other read-only-API tests in this codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _seed_finding(
    db_engine, *, system_id: str | None = None, window_offset_days: int = 0
) -> tuple[str, str]:
    """Returns (system_id, population_finding_id). `window_offset_days`
    shifts `window_start`/`window_end` (default: the original, unshifted
    window every pre-existing call site still gets) -- needed whenever a
    caller seeds more than one finding for the *same* `system_id`, since
    `population_findings`' own `UNIQUE (population_policy_id, system_id,
    window_start, window_end)` constraint (migration `0015`,
    `docs/milestones/M6.md` §13.13) otherwise rejects the second call as a
    duplicate/overlapping run for that system+window -- exactly as
    designed."""
    with Session(db_engine) as session:
        if system_id is None:
            system_id = SystemRepository().create(session, name=f"finding-api-system-{uuid4()}").id
        offset = timedelta(days=window_offset_days)
        finding = PopulationFinding(
            population_finding_id=f"pf-{uuid4()}",
            population_policy_id="adverse-impact-ratio",
            population_policy_version="0.1.0",
            system_id=system_id,
            window_start=datetime(2026, 1, 1, tzinfo=UTC) + offset,
            window_end=datetime(2026, 1, 2, tzinfo=UTC) + offset,
            outcome=PopulationFindingOutcome.FLAGGED,
            metric_values={"race:Black": 0.75},
            classification_snapshot={"race": "DIRECT"},
            rationale="test rationale",
            # A unique `evaluated_at`, not a fixed date -- see
            # `test_admin_population_finding_reviews_api.py`'s identical
            # comment (already in place before M15) for why: this
            # "deadbeef" (non-cryptographic) signature and
            # `test_verify_population_findings_postgres.py`'s own
            # genuinely-signed record both sort by `evaluated_at` (now,
            # since M15, with `id` as a deterministic tiebreaker rather
            # than an arbitrary one) -- a fixed, shared timestamp here
            # lets this row race that one for read order across files in
            # the same shared, never-truncated table.
            evaluated_at=datetime.now(UTC),
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


# --- M15: pagination (docs/milestones/M15.md §5.1/§7) ---


def test_list_respects_limit(api_client: TestClient, db_engine) -> None:
    system_id, _first = _seed_finding(db_engine)
    _seed_finding(db_engine, system_id=system_id, window_offset_days=1)
    _seed_finding(db_engine, system_id=system_id, window_offset_days=2)

    response = api_client.get(
        "/v1/admin/population-findings", params={"system_id": system_id, "limit": 2}
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_respects_offset(api_client: TestClient, db_engine) -> None:
    system_id, _first = _seed_finding(db_engine)
    _seed_finding(db_engine, system_id=system_id, window_offset_days=1)

    first_page = api_client.get(
        "/v1/admin/population-findings", params={"system_id": system_id, "limit": 1}
    )
    second_page = api_client.get(
        "/v1/admin/population-findings",
        params={"system_id": system_id, "limit": 1, "offset": 1},
    )

    assert first_page.json()[0]["id"] != second_page.json()[0]["id"]


def test_list_with_limit_zero_is_422(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-findings", params={"limit": 0})

    assert response.status_code == 422


def test_list_with_limit_over_the_ceiling_is_422(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-findings", params={"limit": 1001})

    assert response.status_code == 422


def test_list_with_negative_offset_is_422(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-findings", params={"offset": -1})

    assert response.status_code == 422


def test_list_omitting_limit_and_offset_is_unaffected_by_this_milestone(
    api_client: TestClient, db_engine
) -> None:
    """M15 §12.1 option (a): the backward-compatibility guarantee itself --
    omitting both parameters returns every matching row, exactly as before
    this milestone."""
    _system_id, finding_id = _seed_finding(db_engine)

    response = api_client.get("/v1/admin/population-findings")

    assert response.status_code == 200
    assert finding_id in {f["id"] for f in response.json()}
