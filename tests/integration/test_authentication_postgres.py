"""Authentication & Authorization — architecture (no numbered section; see
`docs/milestones/M13.md` Sourcing note), M13. Real Postgres, real HTTP.
CI-only (see `conftest.requires_postgres`).

Every test here constructs its own `Settings(..., AUTH_ENABLED=True)` app
instance explicitly, mirroring `requires_admin_postgres`'s own "opt in
per test file, not suite-wide" shape — `tests/conftest.py`'s own
`test_settings`/`api_client` fixtures pin `AUTH_ENABLED=False`
specifically so the rest of this platform's suite stays unaware this
milestone exists (`docs/milestones/M13.md` §5.7).

Covers: `PrincipalRepository` CRUD/revocation; `get_current_principal`/
`require_role` against a real provisioned principal (missing/invalid/
revoked credential, wrong role, right role); the
`POST /v1/auth/session`/`logout` cookie flow; ingestion's `INGESTION`-or-
`ADMIN` gate; and the `reviewer`-sourced-from-principal/rejected-on-
mismatch behavior from §5.6.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gov_platform.access.tokens import hash_token
from gov_platform.api.app import create_app
from gov_platform.config.settings import Settings
from gov_platform.db.repositories.principal import PrincipalRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.principal import Principal, PrincipalRole
from gov_platform.schemas.verdict import GovernanceVerdict, VerdictStatus
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _create_principal(db_engine, *, name: str, role: PrincipalRole) -> tuple[Principal, str]:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, token = repository.create(session, name=name, role=role)
        session.commit()
    return principal, token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_client(postgres_url: str) -> TestClient:
    # base_url="https://testserver": the session cookie is set with
    # Secure=True (correctly, for a real deployment -- docs/milestones/M13.md
    # §5.5), which httpx's own cookie jar will not retain/resend over an
    # http:// origin. TestClient is an ASGI transport, not a real network
    # call, so this is purely nominal for scheme purposes -- the standard,
    # documented fix for testing a Secure cookie through Starlette's
    # TestClient, not a weakening of the cookie's own Secure flag.
    app = create_app(settings=Settings(DATABASE_URL=postgres_url, AUTH_ENABLED=True))
    return TestClient(app, base_url="https://testserver")


# --- PrincipalRepository -----------------------------------------------


def test_create_returns_the_plaintext_token_which_looks_up_via_its_hash(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.REVIEWER
        )
        session.commit()

    assert len(token) > 32
    with Session(db_engine) as session:
        found = repository.get_by_token_hash(session, hash_token(token))
    assert found is not None
    assert found.id == principal.id


def test_get_by_token_hash_does_not_match_on_the_plaintext_token_itself(db_engine) -> None:
    """`token_hash` stores only the digest -- looking up by the raw
    plaintext token (instead of its hash) must never match, confirming
    the plaintext itself was never persisted verbatim anywhere."""
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        _principal, token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.REVIEWER
        )
        session.commit()

    with Session(db_engine) as session:
        found = repository.get_by_token_hash(session, token)
    assert found is None


def test_get_by_token_hash_returns_none_for_an_unknown_hash(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        found = repository.get_by_token_hash(session, "not-a-real-hash")
    assert found is None


def test_revoke_sets_revoked_at(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, _token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.ADMIN
        )
        session.commit()

    with Session(db_engine) as session:
        revoked = repository.revoke(session, principal.id)
        session.commit()

    assert revoked.revoked_at is not None


def test_revoke_an_already_revoked_principal_raises_value_error(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, _token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.ADMIN
        )
        session.commit()
    with Session(db_engine) as session:
        repository.revoke(session, principal.id)
        session.commit()

    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.revoke(session, principal.id)


def test_revoke_an_unknown_principal_raises_value_error(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session, pytest.raises(ValueError):
        repository.revoke(session, str(uuid4()))


def test_list_includes_a_newly_created_principal(db_engine) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, _token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
        )
        session.commit()

    with Session(db_engine) as session:
        principals = repository.list(session)
    assert any(p.id == principal.id for p in principals)


# --- get_current_principal / require_role, via a real endpoint ---------


def test_a_request_with_no_credential_is_rejected_with_401(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/admin/systems")
    assert response.status_code == 401


def test_a_request_with_an_unknown_token_is_rejected_with_401(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/admin/systems", headers=_bearer("not-a-real-token"))
    assert response.status_code == 401


def test_a_non_bearer_authorization_header_falls_through_to_no_credential_401(
    auth_client: TestClient,
) -> None:
    """`_extract_token` checks the `Bearer` scheme specifically -- a
    non-`Bearer` `Authorization` header (e.g. `Basic ...`) must not be
    treated as a credential, falling through to "no credential" (401),
    not a crash or a false-positive match."""
    response = auth_client.get("/v1/admin/systems", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


def test_a_request_with_a_revoked_principals_token_is_rejected_with_401(
    auth_client: TestClient, db_engine
) -> None:
    principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.ADMIN
    )
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        repository.revoke(session, principal.id)
        session.commit()

    response = auth_client.get("/v1/admin/systems", headers=_bearer(token))
    assert response.status_code == 401


def test_a_read_only_principal_can_list_systems(auth_client: TestClient, db_engine) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    response = auth_client.get("/v1/admin/systems", headers=_bearer(token))
    assert response.status_code == 200


def test_a_read_only_principal_cannot_register_a_system(auth_client: TestClient, db_engine) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    response = auth_client.post(
        "/v1/admin/systems", headers=_bearer(token), json={"name": f"sys-{uuid4()}"}
    )
    assert response.status_code == 403


def test_an_admin_principal_can_register_a_system(auth_client: TestClient, db_engine) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.ADMIN
    )
    response = auth_client.post(
        "/v1/admin/systems", headers=_bearer(token), json={"name": f"sys-{uuid4()}"}
    )
    assert response.status_code == 201


# --- Ingestion's INGESTION-or-ADMIN gate --------------------------------


def test_ingestion_with_no_credential_is_rejected_with_401(
    auth_client: TestClient, synthetic_payload_json: dict[str, object]
) -> None:
    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"
    response = auth_client.post("/v1/ingestion/events/synthetic", json=payload)
    assert response.status_code == 401


def test_ingestion_with_a_read_only_credential_is_rejected_with_403(
    auth_client: TestClient, db_engine, synthetic_payload_json: dict[str, object]
) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"
    response = auth_client.post(
        "/v1/ingestion/events/synthetic", headers=_bearer(token), json=payload
    )
    assert response.status_code == 403


def test_ingestion_with_an_ingestion_credential_succeeds(
    auth_client: TestClient, db_engine, synthetic_payload_json: dict[str, object]
) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.INGESTION
    )
    payload = dict(synthetic_payload_json)
    payload["source_event_id"] = f"evt-{uuid4()}"
    response = auth_client.post(
        "/v1/ingestion/events/synthetic", headers=_bearer(token), json=payload
    )
    assert response.status_code == 201


# --- POST /v1/auth/session and /v1/auth/logout --------------------------


def test_session_with_a_valid_token_sets_a_cookie_that_authenticates_subsequent_requests(
    auth_client: TestClient, db_engine
) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    session_response = auth_client.post("/v1/auth/session", json={"token": token})
    assert session_response.status_code == 204
    assert "gov_platform_session" in session_response.cookies

    # The cookie jar carries forward automatically on the same TestClient.
    response = auth_client.get("/v1/admin/systems")
    assert response.status_code == 200


def test_session_with_an_invalid_token_is_rejected_with_401(auth_client: TestClient) -> None:
    response = auth_client.post("/v1/auth/session", json={"token": "not-a-real-token"})
    assert response.status_code == 401


def test_logout_clears_the_cookie_and_subsequent_requests_are_unauthenticated(
    auth_client: TestClient, db_engine
) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    auth_client.post("/v1/auth/session", json={"token": token})
    logout_response = auth_client.post("/v1/auth/logout")
    assert logout_response.status_code == 204

    response = auth_client.get("/v1/admin/systems")
    assert response.status_code == 401


def test_logout_does_not_revoke_the_underlying_token(auth_client: TestClient, db_engine) -> None:
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.READ_ONLY
    )
    auth_client.post("/v1/auth/session", json={"token": token})
    auth_client.post("/v1/auth/logout")

    # The same token still works as a bearer header -- logging out of the
    # dashboard session never revokes API access (docs/milestones/M13.md §5.5).
    response = auth_client.get("/v1/admin/systems", headers=_bearer(token))
    assert response.status_code == 200


# --- reviewer sourced from the authenticated principal (§5.6/§13.13) ---


def _new_verdict_review_id(evidence_store, make_decision_event, db_engine) -> str:
    """An `ESCALATE_FOR_REVIEW` verdict, auto-queuing a real `VerdictReview`
    (`EvidenceStore._queue_verdict_review`, M9) -- mirrors
    `test_verdict_reviews_postgres.py`'s own severity-filter seeding."""
    event = make_decision_event(event_id=f"evt-{uuid4()}")
    verdict_id = str(uuid4())
    finding = Finding(
        finding_id=f"find-{verdict_id}",
        decision_event_id=event.event_id,
        policy_id="always-allow",
        policy_version="0.1.0",
        outcome=FindingOutcome.FLAGGED,
        confidence=1.0,
        rationale="test",
        metric_values={},
        evaluated_at=event.occurred_at,
    )
    verdict = GovernanceVerdict(
        verdict_id=verdict_id,
        decision_event_id=event.event_id,
        status=VerdictStatus.ESCALATE_FOR_REVIEW,
        findings=[finding],
        created_at=event.occurred_at,
    )
    evidence_store.append(event, verdict)

    review_repository = VerdictReviewRepository()
    with Session(db_engine) as session:
        reviews = review_repository.list_all(session)
    matching = [r for r in reviews if r.verdict_id == verdict_id]
    assert matching, (
        "EvidenceStore.append did not queue a VerdictReview for an ESCALATE_FOR_REVIEW verdict"
    )
    return matching[0].id


def test_resolve_verdict_review_sources_reviewer_from_the_authenticated_principal(
    auth_client: TestClient, db_engine, evidence_store, make_decision_event
) -> None:
    review_id = _new_verdict_review_id(evidence_store, make_decision_event, db_engine)
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.REVIEWER
    )

    claim_response = auth_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/claim", headers=_bearer(token), json={}
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["reviewer"] == _principal.name

    resolve_response = auth_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/resolve",
        headers=_bearer(token),
        json={"resolution": "CONFIRMED", "notes": "a real disparity"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["reviewer"] == _principal.name


def test_resolve_verdict_review_rejects_a_mismatched_reviewer_with_422(
    auth_client: TestClient, db_engine, evidence_store, make_decision_event
) -> None:
    review_id = _new_verdict_review_id(evidence_store, make_decision_event, db_engine)
    _principal, token = _create_principal(
        db_engine, name=f"jane-{uuid4()}", role=PrincipalRole.REVIEWER
    )

    claim_response = auth_client.post(
        f"/v1/admin/verdict-reviews/{review_id}/claim",
        headers=_bearer(token),
        json={"reviewer": "someone-else"},
    )
    assert claim_response.status_code == 422
