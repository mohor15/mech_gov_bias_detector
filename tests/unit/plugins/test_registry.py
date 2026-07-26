"""`plugins.registry` — pure in-process logic, no DB.

Fake plugins are registered via a fixture with explicit teardown, not a
module-level `@register_adapter`/`@register_policy` decorator: the real
registry is process-global, shared for the whole test session, and
`api/ingestion/routes.py`'s `build_ingestion_router()` iterates *every*
registered adapter when any test's `create_app()` runs. A module-level
registration would leak a fake, non-Pydantic payload type into every
other test's route generation for the rest of the session and crash
FastAPI's schema generation there instead of here — this fixture's
teardown (`unregister_adapter`/`unregister_policy`) is what prevents that.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import BaseModel

from gov_platform.adapters.base import Adapter
from gov_platform.plugins.registry import (
    get_adapter_class,
    get_policy_class,
    known_adapter_keys,
    known_policy_keys,
    register_adapter,
    register_policy,
    unregister_adapter,
    unregister_policy,
)
from gov_platform.policy_engine.base import Policy
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding


class _FakePayload(BaseModel):
    pass


class _FakeAdapter(Adapter[_FakePayload]):
    adapter_id = "test-fake-adapter"
    version = "0.0.1"
    governing_policy_id = "test-fake-policy"

    def translate(self, raw_payload: _FakePayload) -> DecisionEvent:
        raise NotImplementedError


class _FakePolicy(Policy):
    policy_id = "test-fake-policy"
    version = "0.0.1"

    def evaluate(self, event: DecisionEvent) -> Finding:
        raise NotImplementedError


@pytest.fixture
def registered_fake_adapter() -> Iterator[type[_FakeAdapter]]:
    register_adapter(_FakeAdapter)
    try:
        yield _FakeAdapter
    finally:
        unregister_adapter(_FakeAdapter.adapter_id, _FakeAdapter.version)


@pytest.fixture
def registered_fake_policy() -> Iterator[type[_FakePolicy]]:
    register_policy(_FakePolicy)
    try:
        yield _FakePolicy
    finally:
        unregister_policy(_FakePolicy.policy_id, _FakePolicy.version)


def test_register_adapter_makes_it_findable_by_id_and_version(
    registered_fake_adapter: type[_FakeAdapter],
) -> None:
    assert get_adapter_class("test-fake-adapter", "0.0.1") is registered_fake_adapter


def test_register_policy_makes_it_findable_by_id_and_version(
    registered_fake_policy: type[_FakePolicy],
) -> None:
    assert get_policy_class("test-fake-policy", "0.0.1") is registered_fake_policy


def test_unknown_adapter_returns_none() -> None:
    assert get_adapter_class("does-not-exist", "0.0.1") is None


def test_unknown_policy_returns_none() -> None:
    assert get_policy_class("does-not-exist", "0.0.1") is None


def test_a_known_version_mismatch_returns_none(
    registered_fake_adapter: type[_FakeAdapter],
) -> None:
    assert get_adapter_class("test-fake-adapter", "9.9.9") is None


def test_known_adapter_keys_includes_the_registered_fake(
    registered_fake_adapter: type[_FakeAdapter],
) -> None:
    assert ("test-fake-adapter", "0.0.1") in known_adapter_keys()


def test_known_policy_keys_includes_the_registered_fake(
    registered_fake_policy: type[_FakePolicy],
) -> None:
    assert ("test-fake-policy", "0.0.1") in known_policy_keys()


def test_unregister_adapter_makes_it_unfindable_again() -> None:
    register_adapter(_FakeAdapter)
    unregister_adapter(_FakeAdapter.adapter_id, _FakeAdapter.version)

    assert get_adapter_class("test-fake-adapter", "0.0.1") is None
    assert ("test-fake-adapter", "0.0.1") not in known_adapter_keys()


def test_register_adapter_decorator_returns_the_class_unchanged(
    registered_fake_adapter: type[_FakeAdapter],
) -> None:
    assert registered_fake_adapter.adapter_id == "test-fake-adapter"
    assert registered_fake_adapter.governing_policy_id == "test-fake-policy"


def test_the_two_real_first_party_adapters_are_registered_once_bootstrapped() -> None:
    from gov_platform.plugins.bootstrap import bootstrap_plugins

    bootstrap_plugins()

    assert ("synthetic", "0.1.0") in known_adapter_keys()
    assert ("credit-scorecard", "0.1.0") in known_adapter_keys()


def test_the_two_real_first_party_policies_are_registered_once_bootstrapped() -> None:
    from gov_platform.plugins.bootstrap import bootstrap_plugins

    bootstrap_plugins()

    assert ("always-allow", "0.1.0") in known_policy_keys()
    assert ("direct-attribute-in-inputs", "0.1.0") in known_policy_keys()
