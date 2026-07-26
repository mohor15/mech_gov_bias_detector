"""Shadow policy execution — architecture §6, M3. Real Postgres, real
HTTP. CI-only (see conftest.requires_postgres).

The core guarantee under test: a `SHADOW`-state policy is evaluated
against every real event its adapter handles, its `Finding` lands in
`shadow_findings`, and the response the caller actually receives is
completely unaffected by what it decided — see
`docs/milestones/M3.md` §13.3. The fake shadow policy below always
returns `FLAGGED`, the opposite of what the real `PRODUCTION`
`direct-attribute-in-inputs` policy decides for a well-formed payload —
so if shadow output ever leaked into the served Verdict, this test would
plainly fail by seeing `FLAGGED` instead of `ALLOW`, not require a subtler
assertion to notice.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.plugins.registry import register_policy, unregister_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.plugin_registration import PluginType
from tests.conftest import requires_postgres

pytestmark = requires_postgres

# plugin_registrations is never truncated between test runs (same posture
# as decision_events, evidence_chain, etc.) -- a fixed version string
# would collide with the row a previous run already inserted the moment
# this test ran twice against the same database, so each version here
# includes a fresh uuid computed once at module-import time.
_SHADOW_TEST_VERSION = f"test-shadow-{uuid4()}"


class _AlwaysFlagsShadowPolicy(Policy):
    """Shares `direct-attribute-in-inputs`'s policy_id (what
    `CreditScorecardAdapter.governing_policy_id` names) but a distinct
    version, so it can be registered as a second, SHADOW-state candidate
    alongside the real PRODUCTION `0.1.0`."""

    policy_id = "direct-attribute-in-inputs"
    version = _SHADOW_TEST_VERSION

    def evaluate(self, event: DecisionEvent) -> Finding:
        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.FLAGGED,
            confidence=1.0,
            rationale="shadow test policy always flags",
            metric_values={},
            evaluated_at=datetime.now(UTC),
        )


@pytest.fixture
def shadow_policy_registration(db_engine: Engine) -> Iterator[str]:
    register_policy(_AlwaysFlagsShadowPolicy)
    repository = PluginRegistrationRepository()
    with Session(db_engine) as session:
        registration = repository.create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id=_AlwaysFlagsShadowPolicy.policy_id,
            version=_AlwaysFlagsShadowPolicy.version,
        )
        registration = repository.promote(session, registration.id)  # DRAFT -> SHADOW
        session.commit()

    try:
        yield registration.id
    finally:
        unregister_policy(_AlwaysFlagsShadowPolicy.policy_id, _AlwaysFlagsShadowPolicy.version)


def test_shadow_policy_finding_is_persisted_and_does_not_affect_the_verdict(
    api_client: TestClient,
    credit_scorecard_payload_json: dict[str, object],
    shadow_policy_registration: str,
    db_engine: Engine,
) -> None:
    payload = dict(credit_scorecard_payload_json)
    payload["decision_id"] = f"score-{uuid4()}"

    response = api_client.post("/v1/ingestion/events/credit-scorecard", json=payload)

    assert response.status_code == 201
    # The real PRODUCTION policy's honest answer for a well-formed
    # payload -- proves the FLAGGED-always shadow policy had zero
    # influence on what was actually served.
    assert response.json()["status"] == "ALLOW"

    with Session(db_engine) as session:
        shadow_findings = ShadowFindingRepository().list_by_decision_event(
            session, payload["decision_id"]
        )

    matching = [f for f in shadow_findings if f.policy_version == _SHADOW_TEST_VERSION]
    assert len(matching) == 1
    assert matching[0].outcome is FindingOutcome.FLAGGED


def test_a_raising_shadow_policy_does_not_break_real_ingestion(
    api_client: TestClient,
    credit_scorecard_payload_json: dict[str, object],
    db_engine: Engine,
) -> None:
    class _AlwaysRaisesShadowPolicy(Policy):
        policy_id = "direct-attribute-in-inputs"
        version = f"test-shadow-raises-{uuid4()}"

        def evaluate(self, event: DecisionEvent) -> Finding:
            raise RuntimeError("simulated shadow policy bug")

    register_policy(_AlwaysRaisesShadowPolicy)
    repository = PluginRegistrationRepository()
    try:
        with Session(db_engine) as session:
            registration = repository.create(
                session,
                plugin_type=PluginType.POLICY,
                plugin_id=_AlwaysRaisesShadowPolicy.policy_id,
                version=_AlwaysRaisesShadowPolicy.version,
            )
            repository.promote(session, registration.id)  # DRAFT -> SHADOW
            session.commit()

        payload = dict(credit_scorecard_payload_json)
        payload["decision_id"] = f"score-{uuid4()}"

        response = api_client.post("/v1/ingestion/events/credit-scorecard", json=payload)

        assert response.status_code == 201
        assert response.json()["status"] == "ALLOW"
    finally:
        unregister_policy(_AlwaysRaisesShadowPolicy.policy_id, _AlwaysRaisesShadowPolicy.version)
