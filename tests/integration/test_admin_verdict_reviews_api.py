"""Verdict Reviews Admin API — over real HTTP against a real Postgres.
CI-only (see conftest.requires_postgres).

Seeds a real review by appending a real, `ESCALATE_FOR_REVIEW`/
`RECOMMEND_HOLD` `Verdict` through `EvidenceStore` directly (not through
this API — there is no `POST` here; a review is only ever produced by
`EvidenceStore.append`'s own auto-creation, §3.4), the same "seed through
the real producing path, test the read/action surface separately"
discipline `test_admin_population_findings_api.py` already established
for `PopulationFinding`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.models import VerdictReviewRow
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _verdict(decision_event_id: str, verdict_id: str, status: VerdictStatus) -> GovernanceVerdict:
    finding = Finding(
        finding_id=f"find-{verdict_id}",
        decision_event_id=decision_event_id,
        policy_id="high-debt-ratio-gate",
        policy_version="0.1.0",
        outcome=FindingOutcome.FLAGGED,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return GovernanceVerdict(
        verdict_id=verdict_id,
        decision_event_id=decision_event_id,
        status=status,
        findings=[finding],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _seed_review(
    db_engine, make_decision_event, *, status: VerdictStatus = VerdictStatus.ESCALATE_FOR_REVIEW
) -> tuple[str, str]:
    """Returns (verdict_id, review_id)."""
    evidence_store = EvidenceStore(db_engine)
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    evidence_store.append(event, _verdict(event.event_id, verdict_id, status))

    with Session(db_engine) as session:
        row = session.execute(
            select(VerdictReviewRow).where(VerdictReviewRow.verdict_id == verdict_id)
        ).scalar_one()
    return verdict_id, row.id


def test_appending_an_escalated_verdict_auto_creates_an_open_review(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    response = api_client.get(f"/v1/admin/verdict-reviews/{review_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["verdict"]["status"] == "ESCALATE_FOR_REVIEW"


def test_get_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.get("/v1/admin/verdict-reviews/does-not-exist")

    assert response.status_code == 404


def test_list_includes_a_seeded_review(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    response = api_client.get("/v1/admin/verdict-reviews")

    assert response.status_code == 200
    assert review_id in {r["id"] for r in response.json()}


def test_list_filtered_by_status(api_client: TestClient, db_engine, make_decision_event) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    response = api_client.get("/v1/admin/verdict-reviews", params={"status": "OPEN"})

    assert response.status_code == 200
    assert review_id in {r["id"] for r in response.json()}
    assert all(r["status"] == "OPEN" for r in response.json())


def test_list_filtered_by_severity_returns_only_that_severity(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _escalate_verdict_id, escalate_review_id = _seed_review(
        db_engine, make_decision_event, status=VerdictStatus.ESCALATE_FOR_REVIEW
    )
    _hold_verdict_id, hold_review_id = _seed_review(
        db_engine, make_decision_event, status=VerdictStatus.RECOMMEND_HOLD
    )

    response = api_client.get("/v1/admin/verdict-reviews", params={"severity": "RECOMMEND_HOLD"})

    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert hold_review_id in ids
    assert escalate_review_id not in ids
    for review in response.json():
        assert review["verdict"]["status"] == "RECOMMEND_HOLD"


def test_claim_then_resolve_the_full_happy_path(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    claim_response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"}
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["status"] == "IN_REVIEW"
    assert claim_response.json()["reviewer"] == "jane"

    resolve_response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": "a real disparity"},
    )
    assert resolve_response.status_code == 200
    body = resolve_response.json()
    assert body["status"] == "RESOLVED"
    assert body["resolution"] == "CONFIRMED"
    assert body["resolution_notes"] == "a real disparity"


def test_claim_on_an_already_claimed_review_is_409(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)
    api_client.post(f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"})

    response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "someone-else"}
    )

    assert response.status_code == 409


def test_claim_on_an_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/verdict-reviews/does-not-exist/claim", json={"reviewer": "jane"}
    )

    assert response.status_code == 404


def test_release_returns_it_to_open_and_a_different_reviewer_can_claim_it(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)
    api_client.post(f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"})

    release_response = api_client.post(f"/v1/admin/verdict-reviews/{review_id}/release")
    assert release_response.status_code == 200
    assert release_response.json()["status"] == "OPEN"

    claim_response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "someone-else"}
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["reviewer"] == "someone-else"


def test_release_on_an_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/verdict-reviews/does-not-exist/release")

    assert response.status_code == 404


def test_resolve_on_an_unknown_review_is_404(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/admin/verdict-reviews/does-not-exist/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": "n/a"},
    )

    assert response.status_code == 404


def test_release_on_an_item_that_is_not_in_review_is_409(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    response = api_client.post(f"/v1/admin/verdict-reviews/{review_id}/release")

    assert response.status_code == 409


def test_resolve_with_a_reviewer_that_does_not_match_the_claimant_is_409(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)
    api_client.post(f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"})

    response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        json={"reviewer": "someone-else", "resolution": "CONFIRMED", "notes": "test"},
    )

    assert response.status_code == 409


def test_resolve_before_claim_is_409(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)

    response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": "test"},
    )

    assert response.status_code == 409


def test_resolve_with_an_empty_notes_string_is_422(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    _verdict_id, review_id = _seed_review(db_engine, make_decision_event)
    api_client.post(f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"})

    response = api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "CONFIRMED", "notes": ""},
    )

    assert response.status_code == 422


def test_resolving_then_reopening_makes_both_rows_visible_in_the_list(
    api_client: TestClient, db_engine, make_decision_event
) -> None:
    """The reopening path, exercised through the API, not just the
    repository (docs/milestones/M9.md §6.3)."""
    from gov_platform.db.repositories.verdict_review import VerdictReviewRepository

    verdict_id, review_id = _seed_review(db_engine, make_decision_event)
    api_client.post(f"/v1/admin/verdict-reviews/{review_id}/claim", json={"reviewer": "jane"})
    api_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        json={"reviewer": "jane", "resolution": "DISMISSED", "notes": "false positive"},
    )

    with Session(db_engine) as session:
        reopened = VerdictReviewRepository().create(session, verdict_id)
        session.commit()
    assert reopened is not None

    response = api_client.get("/v1/admin/verdict-reviews")
    ids = {r["id"] for r in response.json()}

    assert review_id in ids
    assert reopened.id in ids
    statuses_by_id = {r["id"]: r["status"] for r in response.json()}
    assert statuses_by_id[review_id] == "RESOLVED"
    assert statuses_by_id[reopened.id] == "OPEN"
