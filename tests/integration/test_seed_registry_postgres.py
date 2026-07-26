"""`plugins.seed_registry`'s CLI — mirrors `tests/unit/db/test_migrate.py`'s
pattern of calling `main(argv)` directly. Needs a real Postgres (it
registers/promotes real rows), unlike `db.migrate`'s CLI tests, which run
against a throwaway SQLite file — so this lives in `tests/integration/`,
not `tests/unit/`. CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic import BaseModel

from gov_platform.adapters.base import Adapter
from gov_platform.plugins.registry import register_adapter, unregister_adapter
from gov_platform.plugins.seed_registry import main
from gov_platform.schemas.decision_event import DecisionEvent
from tests.conftest import requires_postgres

pytestmark = requires_postgres


class _FreshTestPayload(BaseModel):
    event_id: str


class _FreshTestAdapter(Adapter[_FreshTestPayload]):
    """Registered in-process only for the duration of one test, never via
    the session-wide seeding fixture -- the four real first-party plugins
    are always already PRODUCTION by the time any test runs (see
    conftest._seed_plugin_registry), so they can't exercise
    `seed_to_production`'s fresh-registration/promotion branches. This one
    has no `plugin_registrations` row at all until `main()` creates it.
    """

    adapter_id = "test-fresh-seed-adapter"
    version = f"1.0.0-{uuid4()}"
    governing_policy_id = "always-allow"

    def translate(self, raw_payload: _FreshTestPayload) -> DecisionEvent:
        raise NotImplementedError


@pytest.fixture
def fresh_test_adapter() -> Iterator[None]:
    register_adapter(_FreshTestAdapter)
    try:
        yield
    finally:
        unregister_adapter(_FreshTestAdapter.adapter_id, _FreshTestAdapter.version)


def test_main_registers_and_promotes_a_never_before_seen_plugin(
    postgres_url: str, fresh_test_adapter: None, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--database-url", postgres_url])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert (
        f"ADAPTER {_FreshTestAdapter.adapter_id} {_FreshTestAdapter.version}: "
        "promoted to PRODUCTION" in output
    )


def test_main_is_idempotent_on_a_second_run(
    postgres_url: str, fresh_test_adapter: None, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--database-url", postgres_url])
    capsys.readouterr()

    exit_code = main(["--database-url", postgres_url])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert (
        f"ADAPTER {_FreshTestAdapter.adapter_id} {_FreshTestAdapter.version}: "
        "already PRODUCTION" in output
    )


def test_main_seeds_the_four_real_first_party_plugins(
    postgres_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # By the time this runs, the session-wide fixture has already seeded
    # these -- this proves main() reports them correctly either way
    # (already PRODUCTION, in practice), not that this particular call is
    # what did the seeding.
    exit_code = main(["--database-url", postgres_url])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ADAPTER synthetic" in output
    assert "ADAPTER credit-scorecard" in output
    assert "POLICY always-allow" in output
    assert "POLICY direct-attribute-in-inputs" in output
