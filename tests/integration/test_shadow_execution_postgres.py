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
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.plugins.registry import register_policy, unregister_policy
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.plugin_registration import PluginType
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _make_always_flags_shadow_policy() -> type[Policy]:
    """A fresh class per call, with its own fresh version — shares
    `direct-attribute-in-inputs`'s policy_id (one of the two families
    `CreditScorecardAdapter.governing_policy_ids` names) so it registers
    as a second, SHADOW-state candidate alongside the real PRODUCTION
    `0.1.0`. Built fresh per fixture invocation, not a module-level
    singleton: `plugin_registrations` is never truncated between test
    runs, so two tests sharing one fixed version would collide with each
    other within the same run, not just across separate runs.
    """

    class _AlwaysFlagsShadowPolicy(Policy):
        policy_id = "direct-attribute-in-inputs"
        version = f"test-shadow-{uuid4()}"

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

    return _AlwaysFlagsShadowPolicy


@pytest.fixture
def shadow_policy_registration(db_engine: Engine) -> Iterator[type[Policy]]:
    policy_cls = _make_always_flags_shadow_policy()
    register_policy(policy_cls)
    repository = PluginRegistrationRepository()
    with Session(db_engine) as session:
        registration = repository.create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id=policy_cls.policy_id,
            version=policy_cls.version,
        )
        repository.promote(session, registration.id)  # DRAFT -> SHADOW
        session.commit()

    try:
        yield policy_cls
    finally:
        unregister_policy(policy_cls.policy_id, policy_cls.version)


def test_shadow_policy_finding_is_persisted_and_does_not_affect_the_verdict(
    api_client: TestClient,
    credit_scorecard_payload_json: dict[str, object],
    shadow_policy_registration: type[Policy],
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

    matching = [
        f for f in shadow_findings if f.policy_version == shadow_policy_registration.version
    ]
    assert len(matching) == 1
    assert matching[0].outcome is FindingOutcome.FLAGGED


def test_shadow_candidate_for_one_family_does_not_affect_the_other_familys_finding(
    api_client: TestClient,
    credit_scorecard_payload_json: dict[str, object],
    shadow_policy_registration: type[Policy],
    db_engine: Engine,
) -> None:
    # M4: credit-scorecard now has two governing policy families. A
    # SHADOW candidate registered under *one* of them
    # (direct-attribute-in-inputs) must not affect the other
    # (high-debt-ratio-gate)'s independent evaluation, and the real
    # aggregate verdict must still reflect both PRODUCTION findings.
    payload = dict(credit_scorecard_payload_json)
    payload["decision_id"] = f"score-{uuid4()}"
    feature_vector = dict(payload["feature_vector"])  # type: ignore[arg-type]
    feature_vector["debt_to_income"] = 0.55  # only high-debt-ratio-gate objects
    payload["feature_vector"] = feature_vector

    response = api_client.post("/v1/ingestion/events/credit-scorecard", json=payload)

    assert response.status_code == 201
    # FLAGGED because of the real debt-ratio finding, not the shadow
    # candidate's opinion on the unrelated fairness family.
    assert response.json()["status"] == "FLAGGED"

    with Session(db_engine) as session:
        verdict = VerdictRepository().get(session, response.json()["verdict_id"])
        shadow_findings = ShadowFindingRepository().list_by_decision_event(
            session, payload["decision_id"]
        )

    assert verdict is not None
    assert {f.policy_id for f in verdict.findings} == {
        "direct-attribute-in-inputs",
        "high-debt-ratio-gate",
    }
    direct_attribute_finding = next(
        f for f in verdict.findings if f.policy_id == "direct-attribute-in-inputs"
    )
    assert direct_attribute_finding.outcome is FindingOutcome.CLEAR

    shadow_matching = [
        f for f in shadow_findings if f.policy_version == shadow_policy_registration.version
    ]
    assert len(shadow_matching) == 1
    assert shadow_matching[0].outcome is FindingOutcome.FLAGGED


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
