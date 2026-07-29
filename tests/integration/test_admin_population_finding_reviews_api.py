"""Population Finding Reviews Admin API — over real HTTP against a real
Postgres. CI-only (see conftest.requires_postgres).

Mirrors `test_admin_verdict_reviews_api.py` exactly, for
`PopulationFinding` instead of `Verdict`. Seeds a real `FLAGGED`
`PopulationFinding` directly via `PopulationFindingRepository`, then calls
`population_finding_review_repository.create` directly to seed the review
row (there is no batch job invocation in this file — unlike
`EvidenceStore.append`, which auto-creates a review as a side effect,
seeding a `PopulationFinding` via the repository alone does not, since
`run_policies.py`'s own decoupled review-creation step lives in
`run_policies.py` itself, not in `PopulationFindingRepository`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _seed_review(db_engine) -> tuple[str, str]:
    """Returns (population_finding_id, review_id)."""
    with Session(db_engine) as session:
        system_id = SystemRepository().create(session, name=f"review-api-system-{uuid4()}").id
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
        review = PopulationFindingReviewRepository().create(session, finding.population_finding_id)
        session.commit()
    assert review is not None
    return finding.population_finding_id, review.id


def test_get_a_seeded_review(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)

    response = api_client.get(f"/v1/admin/population-finding-reviews/{review_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["population_finding"]["outcome"] == "FLAGGED"


def test_get_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/population-finding-reviews/does-not-exist")

    assert response.status_code == 404


def test_list_includes_a_seeded_review(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)

    response = api_client.get("/v1/admin/population-finding-reviews")

    assert response.status_code == 200
    assert review_id in {r["id"] for r in response.json()}


def test_list_filtered_by_status(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)

    response = api_client.get("/v1/admin/population-finding-reviews", params={"status": "OPEN"})

    assert response.status_code == 200
    assert review_id in {r["id"] for r in response.json()}


def test_claim_then_resolve_the_full_happy_path(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)

    claim_response = api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["status"] == "IN_REVIEW"

    resolve_response = api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": "a real disparity"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "RESOLVED"


def test_claim_on_an_already_claimed_review_is_409(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)
    api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )

    response = api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim",
        json={"reviewer": "someone-else"},
    )

    assert response.status_code == 409


def test_release_returns_it_to_open(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)
    api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )

    response = api_client.post(f"/v1/admin/population-finding-reviews/{review_id}/release")

    assert response.status_code == 200
    assert response.json()["status"] == "OPEN"


def test_release_on_an_item_that_is_not_in_review_is_409(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)

    response = api_client.post(f"/v1/admin/population-finding-reviews/{review_id}/release")

    assert response.status_code == 409


def test_resolve_with_a_reviewer_that_does_not_match_the_claimant_is_409(
    api_client: TestClient, db_engine
) -> None:
    _finding_id, review_id = _seed_review(db_engine)
    api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )

    response = api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/resolve",
        json={"reviewer": "someone-else", "resolution": "CONFIRMED", "notes": "test"},
    )

    assert response.status_code == 409


def test_resolve_with_an_empty_notes_string_is_422(api_client: TestClient, db_engine) -> None:
    _finding_id, review_id = _seed_review(db_engine)
    api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )

    response = api_client.post(
        f"/v1/admin/population-finding-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": ""},
    )

    assert response.status_code == 422
