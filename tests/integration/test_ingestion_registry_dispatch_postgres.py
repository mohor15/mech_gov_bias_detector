"""Registry-driven ingestion dispatch edge cases — a never-registered (or
still-`DRAFT`) adapter rejects real traffic, an adapter with no
`PRODUCTION` policy is a clean 503, and a genuinely slow plugin trips the
sandbox timeout into a 504. Real Postgres, real HTTP. CI-only (see
conftest.requires_postgres).

Each scenario registers a small, disposable fake adapter/policy in the
in-process registry (with explicit teardown — see
tests/unit/plugins/test_registry.py for why) rather than touching any of
the four real first-party plugins, which are already seeded to
`PRODUCTION` for the whole test session.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gov_platform.adapters.base import Adapter
from gov_platform.api.app import create_app
from gov_platform.config.settings import Settings
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.session import create_db_engine
from gov_platform.plugins import sandbox
from gov_platform.plugins.registry import (
    register_adapter,
    register_policy,
    unregister_adapter,
    unregister_policy,
)
from gov_platform.plugins.seed_registry import seed_policy_binding
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding, FindingOutcome
from gov_platform.schemas.plugin_registration import PluginType
from gov_platform.schemas.policy_binding import PolicyBindingLifecycleState, PolicySeverity
from tests.conftest import requires_postgres

pytestmark = requires_postgres


class _TestPayload(BaseModel):
    event_id: str


def _translate(payload: _TestPayload, system_id: str) -> DecisionEvent:
    return DecisionEvent(
        event_id=payload.event_id,
        system_id=system_id,
        decision_type="test",
        subject_ref="subject",
        occurred_at=datetime.now(UTC),
        ingested_at=datetime.now(UTC),
    )


class _NeverRegisteredAdapter(Adapter[_TestPayload]):
    adapter_id = "test-never-registered-adapter"
    version = "1.0.0"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        raise NotImplementedError  # never reached -- rejected before this runs


@pytest.fixture
def app_with_unregistered_adapter(test_settings: Settings) -> Iterator[TestClient]:
    register_adapter(_NeverRegisteredAdapter)
    try:
        # No plugin_registrations row is ever created for it -- proves
        # "never registered" is rejected the same way an explicit DRAFT
        # registration would be.
        yield TestClient(create_app(settings=test_settings))
    finally:
        unregister_adapter(_NeverRegisteredAdapter.adapter_id, _NeverRegisteredAdapter.version)


def test_a_never_registered_adapter_rejects_traffic_with_503(
    app_with_unregistered_adapter: TestClient,
) -> None:
    response = app_with_unregistered_adapter.post(
        "/v1/ingestion/events/test-never-registered-adapter", json={"event_id": "evt-1"}
    )

    assert response.status_code == 503
    assert "not yet accepting production traffic" in response.json()["detail"]


class _OrphanPolicyAdapter(Adapter[_TestPayload]):
    adapter_id = "test-orphan-policy-adapter"
    # plugin_registrations is never truncated between test runs -- a
    # fixed version would collide with a previous run's row the moment
    # this test executed twice against the same database.
    version = f"1.0.0-{uuid4()}"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-orphan-system")


_ORPHAN_POLICY_ID = "test-policy-family-nothing-is-registered-under"


@pytest.fixture
def app_with_orphan_policy_adapter(
    test_settings: Settings, postgres_url: str
) -> Iterator[TestClient]:
    register_adapter(_OrphanPolicyAdapter)
    repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_OrphanPolicyAdapter.adapter_id,
            version=_OrphanPolicyAdapter.version,
        )
        registration = repository.promote(session, registration.id)
        repository.promote(session, registration.id)
        # M5: policy_bindings is keyed by (adapter_id, policy_id) with no
        # version component, and adapter_id here is a fixed string --
        # seed_policy_binding's idempotent check-first is what keeps this
        # safe to run twice against the same never-truncated database.
        seed_policy_binding(
            session,
            policy_binding_repository,
            adapter_id=_OrphanPolicyAdapter.adapter_id,
            policy_id=_ORPHAN_POLICY_ID,
            severity=PolicySeverity.LOW,
        )
        session.commit()

    try:
        yield TestClient(create_app(settings=test_settings))
    finally:
        unregister_adapter(_OrphanPolicyAdapter.adapter_id, _OrphanPolicyAdapter.version)


def test_an_adapter_with_no_production_policy_returns_503(
    app_with_orphan_policy_adapter: TestClient,
) -> None:
    response = app_with_orphan_policy_adapter.post(
        "/v1/ingestion/events/test-orphan-policy-adapter",
        json={"event_id": f"evt-{uuid4()}"},
    )

    assert response.status_code == 503
    assert "no PRODUCTION policy registered" in response.json()["detail"]


class _UnboundAdapter(Adapter[_TestPayload]):
    """M5: a real, PRODUCTION-promoted adapter with zero policy_bindings
    rows at all -- distinct from `_OrphanPolicyAdapter`, which has a
    binding pointing at a policy that was never registered. This one has
    no binding whatsoever."""

    adapter_id = "test-unbound-adapter"
    version = f"1.0.0-{uuid4()}"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-unbound-system")


@pytest.fixture
def app_with_unbound_adapter(test_settings: Settings, postgres_url: str) -> Iterator[TestClient]:
    register_adapter(_UnboundAdapter)
    repository = PluginRegistrationRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_UnboundAdapter.adapter_id,
            version=_UnboundAdapter.version,
        )
        registration = repository.promote(session, registration.id)
        repository.promote(session, registration.id)
        session.commit()

    try:
        yield TestClient(create_app(settings=test_settings))
    finally:
        unregister_adapter(_UnboundAdapter.adapter_id, _UnboundAdapter.version)


def test_an_adapter_with_zero_policy_bindings_returns_503(
    app_with_unbound_adapter: TestClient,
) -> None:
    response = app_with_unbound_adapter.post(
        "/v1/ingestion/events/test-unbound-adapter",
        json={"event_id": f"evt-{uuid4()}"},
    )

    assert response.status_code == 503
    assert "has no active policy bindings" in response.json()["detail"]


class _RolledBackPolicy(Policy):
    """Registered, promoted to PRODUCTION, then unregistered from the
    in-process registry while its database row still says PRODUCTION --
    simulates a code rollback that wasn't paired with a lifecycle
    demotion. `evaluate` is never actually reached; the route must catch
    this before calling it."""

    policy_id = "test-rolled-back-policy"
    version = f"1.0.0-{uuid4()}"

    def evaluate(self, event: DecisionEvent) -> Finding:
        raise NotImplementedError


class _RolledBackPolicyAdapter(Adapter[_TestPayload]):
    adapter_id = "test-rolled-back-policy-adapter"
    version = f"1.0.0-{uuid4()}"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-rolled-back-system")


@pytest.fixture
def app_with_rolled_back_production_policy(
    test_settings: Settings, postgres_url: str
) -> Iterator[TestClient]:
    register_adapter(_RolledBackPolicyAdapter)
    register_policy(_RolledBackPolicy)
    repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        adapter_registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_RolledBackPolicyAdapter.adapter_id,
            version=_RolledBackPolicyAdapter.version,
        )
        adapter_registration = repository.promote(session, adapter_registration.id)
        repository.promote(session, adapter_registration.id)

        policy_registration = repository.create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id=_RolledBackPolicy.policy_id,
            version=_RolledBackPolicy.version,
        )
        policy_registration = repository.promote(session, policy_registration.id)
        repository.promote(session, policy_registration.id)
        seed_policy_binding(
            session,
            policy_binding_repository,
            adapter_id=_RolledBackPolicyAdapter.adapter_id,
            policy_id=_RolledBackPolicy.policy_id,
            severity=PolicySeverity.LOW,
        )
        session.commit()

    # The rollback: the DB still says PRODUCTION, but this process no
    # longer has code for it.
    unregister_policy(_RolledBackPolicy.policy_id, _RolledBackPolicy.version)

    try:
        yield TestClient(create_app(settings=test_settings))
    finally:
        unregister_adapter(_RolledBackPolicyAdapter.adapter_id, _RolledBackPolicyAdapter.version)


def test_a_production_policy_no_longer_deployed_in_process_returns_503(
    app_with_rolled_back_production_policy: TestClient,
) -> None:
    response = app_with_rolled_back_production_policy.post(
        "/v1/ingestion/events/test-rolled-back-policy-adapter",
        json={"event_id": f"evt-{uuid4()}"},
    )

    assert response.status_code == 503
    assert "no longer deployed in this process" in response.json()["detail"]


class _DeactivatableBoundPolicy(Policy):
    # policy_bindings is keyed by (adapter_id, policy_id) with no version
    # component and is never truncated between test runs -- a fixed
    # policy_id would let a *previous run's own deactivation* (this test's
    # whole point) leak into the next run, since seeding a binding is
    # idempotent and does not reset an existing row's lifecycle_state back
    # to ACTIVE. See tests/integration/test_shadow_execution_postgres.py
    # for the same lesson learned the same way.
    policy_id = f"test-deactivatable-bound-policy-{uuid4()}"
    version = "1.0.0"

    def evaluate(self, event: DecisionEvent) -> Finding:
        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=datetime.now(UTC),
        )


class _DeactivatableBoundAdapter(Adapter[_TestPayload]):
    adapter_id = f"test-deactivatable-bound-adapter-{uuid4()}"
    version = "1.0.0"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-deactivatable-bound-system")


@pytest.fixture
def app_with_deactivatable_binding(
    test_settings: Settings, postgres_url: str
) -> Iterator[tuple[TestClient, str]]:
    """M5: proves deactivating a PolicyBinding takes effect on the very
    next request, no app restart needed -- the same "no redeploy" property
    M3 already established for plugin lifecycle promotion, extended to
    bindings. Yields the binding's id too, so the test can deactivate it
    mid-scenario via the repository directly (the Admin API's own
    activate/deactivate endpoints are already covered end to end in
    tests/integration/test_admin_policy_bindings_api.py)."""
    register_adapter(_DeactivatableBoundAdapter)
    register_policy(_DeactivatableBoundPolicy)
    repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        adapter_registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_DeactivatableBoundAdapter.adapter_id,
            version=_DeactivatableBoundAdapter.version,
        )
        adapter_registration = repository.promote(session, adapter_registration.id)
        repository.promote(session, adapter_registration.id)

        policy_registration = repository.create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id=_DeactivatableBoundPolicy.policy_id,
            version=_DeactivatableBoundPolicy.version,
        )
        policy_registration = repository.promote(session, policy_registration.id)
        repository.promote(session, policy_registration.id)

        binding = policy_binding_repository.create(
            session,
            adapter_id=_DeactivatableBoundAdapter.adapter_id,
            policy_id=_DeactivatableBoundPolicy.policy_id,
            severity=PolicySeverity.LOW,
        )
        session.commit()
        binding_id = binding.id

    try:
        yield TestClient(create_app(settings=test_settings)), binding_id
    finally:
        unregister_adapter(
            _DeactivatableBoundAdapter.adapter_id, _DeactivatableBoundAdapter.version
        )
        unregister_policy(_DeactivatableBoundPolicy.policy_id, _DeactivatableBoundPolicy.version)


def test_deactivating_a_binding_takes_effect_on_the_next_request(
    app_with_deactivatable_binding: tuple[TestClient, str], postgres_url: str
) -> None:
    client, binding_id = app_with_deactivatable_binding
    url = f"/v1/ingestion/events/{_DeactivatableBoundAdapter.adapter_id}"

    first_response = client.post(url, json={"event_id": f"evt-{uuid4()}"})
    assert first_response.status_code == 201
    assert first_response.json()["status"] == "ALLOW"

    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        PolicyBindingRepository().set_lifecycle_state(
            session, binding_id, PolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

    second_response = client.post(url, json={"event_id": f"evt-{uuid4()}"})
    assert second_response.status_code == 503
    assert "has no active policy bindings" in second_response.json()["detail"]


class _NormalPolicy(Policy):
    policy_id = "test-m4-normal-policy"
    version = f"1.0.0-{uuid4()}"

    def evaluate(self, event: DecisionEvent) -> Finding:
        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="test",
            metric_values={},
            evaluated_at=datetime.now(UTC),
        )


class _RaisingPolicy(Policy):
    policy_id = "test-m4-raising-policy"
    version = f"1.0.0-{uuid4()}"

    def evaluate(self, event: DecisionEvent) -> Finding:
        raise RuntimeError("simulated policy failure")


class _TwoPolicyAdapter(Adapter[_TestPayload]):
    """M4: proves a failing PRODUCTION policy fails the whole request
    rather than aggregating a partial finding set, even when it's only
    one of *several* governing policies -- see
    docs/milestones/M4.md §13.5."""

    adapter_id = "test-m4-two-policy-adapter"
    version = f"1.0.0-{uuid4()}"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-m4-two-policy-system")


@pytest.fixture
def app_with_one_raising_production_policy(test_settings: Settings, postgres_url: str):
    register_adapter(_TwoPolicyAdapter)
    register_policy(_NormalPolicy)
    register_policy(_RaisingPolicy)
    repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        adapter_registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_TwoPolicyAdapter.adapter_id,
            version=_TwoPolicyAdapter.version,
        )
        adapter_registration = repository.promote(session, adapter_registration.id)
        repository.promote(session, adapter_registration.id)

        for policy_cls in (_NormalPolicy, _RaisingPolicy):
            policy_registration = repository.create(
                session,
                plugin_type=PluginType.POLICY,
                plugin_id=policy_cls.policy_id,
                version=policy_cls.version,
            )
            policy_registration = repository.promote(session, policy_registration.id)
            repository.promote(session, policy_registration.id)
            seed_policy_binding(
                session,
                policy_binding_repository,
                adapter_id=_TwoPolicyAdapter.adapter_id,
                policy_id=policy_cls.policy_id,
                severity=PolicySeverity.LOW,
            )
        session.commit()

    try:
        yield create_app(settings=test_settings)
    finally:
        unregister_adapter(_TwoPolicyAdapter.adapter_id, _TwoPolicyAdapter.version)
        unregister_policy(_NormalPolicy.policy_id, _NormalPolicy.version)
        unregister_policy(_RaisingPolicy.policy_id, _RaisingPolicy.version)


def test_one_of_several_production_policies_raising_fails_the_whole_request(
    app_with_one_raising_production_policy,
) -> None:
    client = TestClient(app_with_one_raising_production_policy, raise_server_exceptions=False)
    response = client.post(
        "/v1/ingestion/events/test-m4-two-policy-adapter",
        json={"event_id": f"evt-{uuid4()}"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}


class _SlowPolicy(Policy):
    policy_id = "test-slow-policy"
    version = f"1.0.0-{uuid4()}"

    def evaluate(self, event: DecisionEvent) -> Finding:
        time.sleep(0.3)
        return Finding(
            finding_id=str(uuid4()),
            decision_event_id=event.event_id,
            policy_id=self.policy_id,
            policy_version=self.version,
            outcome=FindingOutcome.CLEAR,
            confidence=1.0,
            rationale="unreachable -- times out first",
            metric_values={},
            evaluated_at=datetime.now(UTC),
        )


class _SlowPolicyAdapter(Adapter[_TestPayload]):
    adapter_id = "test-slow-policy-adapter"
    version = f"1.0.0-{uuid4()}"

    def translate(self, raw_payload: _TestPayload) -> DecisionEvent:
        return _translate(raw_payload, "test-slow-system")


@pytest.fixture
def app_with_slow_policy(
    test_settings: Settings, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(sandbox, "DEFAULT_TIMEOUT_SECONDS", 0.05)
    register_adapter(_SlowPolicyAdapter)
    register_policy(_SlowPolicy)
    repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    engine = create_db_engine(postgres_url)
    with Session(engine) as session:
        adapter_registration = repository.create(
            session,
            plugin_type=PluginType.ADAPTER,
            plugin_id=_SlowPolicyAdapter.adapter_id,
            version=_SlowPolicyAdapter.version,
        )
        adapter_registration = repository.promote(session, adapter_registration.id)
        repository.promote(session, adapter_registration.id)

        policy_registration = repository.create(
            session,
            plugin_type=PluginType.POLICY,
            plugin_id=_SlowPolicy.policy_id,
            version=_SlowPolicy.version,
        )
        policy_registration = repository.promote(session, policy_registration.id)
        repository.promote(session, policy_registration.id)
        seed_policy_binding(
            session,
            policy_binding_repository,
            adapter_id=_SlowPolicyAdapter.adapter_id,
            policy_id=_SlowPolicy.policy_id,
            severity=PolicySeverity.LOW,
        )
        session.commit()

    try:
        yield TestClient(create_app(settings=test_settings))
    finally:
        unregister_adapter(_SlowPolicyAdapter.adapter_id, _SlowPolicyAdapter.version)
        unregister_policy(_SlowPolicy.policy_id, _SlowPolicy.version)


def test_a_plugin_exceeding_its_timeout_budget_returns_504(
    app_with_slow_policy: TestClient,
) -> None:
    response = app_with_slow_policy.post(
        "/v1/ingestion/events/test-slow-policy-adapter",
        json={"event_id": f"evt-{uuid4()}"},
    )

    assert response.status_code == 504
    assert "execution budget" in response.json()["detail"]
