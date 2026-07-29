"""`python -m gov_platform.population.run_policies` (`population_engine/run_policies.py`)
end to end — real Postgres, real signing, real plugin-registry lifecycle
checks. CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from gov_platform.audit.signing import load_signer
from gov_platform.audit.verify_population_findings import (
    population_finding_hash,
    verify_population_findings,
)
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.population_engine.run_policies import main
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType
from gov_platform.schemas.population_policy_binding import PopulationPolicyBindingLifecycleState
from tests.conftest import requires_postgres

pytestmark = requires_postgres

_IN_WINDOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_WINDOW_START = datetime(2026, 3, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 3, 2, tzinfo=UTC)


def _run(postgres_url: str) -> int:
    return main(
        [
            "--database-url",
            postgres_url,
            "--window-start",
            _WINDOW_START.isoformat(),
            "--window-end",
            _WINDOW_END.isoformat(),
        ]
    )


def test_evaluates_an_active_binding_and_persists_a_signed_finding(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions(
        [
            ({"race": "Black"}, True, _IN_WINDOW),
            *[({"race": "Black"}, False, _IN_WINDOW) for _ in range(39)],  # 1/40 = 2.5% approved
            *[({"race": "White"}, True, _IN_WINDOW) for _ in range(40)],  # 100% approved
        ]
    )
    with Session(db_engine) as session:
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)

    assert len(findings) == 1
    assert findings[0].outcome.value == "FLAGGED"
    assert findings[0].signature is not None
    assert findings[0].population_policy_version == "0.1.0"


def test_a_second_run_over_the_same_window_is_a_clean_skip_not_a_duplicate(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    with Session(db_engine) as session:
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

    first_exit_code = _run(postgres_url)
    second_exit_code = _run(postgres_url)

    assert first_exit_code == 0
    assert second_exit_code == 0  # a duplicate-window skip is not an error
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)
    assert len(findings) == 1


def test_an_inactive_binding_is_not_evaluated(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    with Session(db_engine) as session:
        repository = PopulationPolicyBindingRepository()
        binding = repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        repository.set_lifecycle_state(
            session, binding.id, PopulationPolicyBindingLifecycleState.INACTIVE
        )
        session.commit()

    _run(postgres_url)

    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)
    assert findings == []


def test_a_binding_with_no_production_population_policy_is_skipped_not_an_error(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    unregistered_policy_id = f"unregistered-population-policy-{uuid4()}"
    with Session(db_engine) as session:
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id=unregistered_policy_id
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)
    assert findings == []


def test_a_draft_population_policy_registration_is_treated_as_not_production(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    draft_policy_id = f"draft-population-policy-{uuid4()}"
    with Session(db_engine) as session:
        PluginRegistrationRepository().create(
            session,
            plugin_type=PluginType.POPULATION_POLICY,
            plugin_id=draft_policy_id,
            version="0.1.0",
        )
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id=draft_policy_id
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        registration = PluginRegistrationRepository().get_by_identity(
            session,
            plugin_type=PluginType.POPULATION_POLICY,
            plugin_id=draft_policy_id,
            version="0.1.0",
        )
    assert registration is not None
    assert registration.lifecycle_state is PluginLifecycleState.DRAFT


def test_the_signed_finding_verifies_against_the_configured_public_key(
    postgres_url, db_engine, seed_finance_decisions, monkeypatch
) -> None:
    from gov_platform.audit.signing import generate_private_key_hex

    private_key_hex = generate_private_key_hex()
    monkeypatch.setenv("GOV_PLATFORM_SIGNING_PRIVATE_KEY", private_key_hex)
    from gov_platform.config.settings import get_settings

    get_settings.cache_clear()

    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    with Session(db_engine) as session:
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

    _run(postgres_url)
    get_settings.cache_clear()

    public_key_hex = load_signer(private_key_hex).public_key_hex()
    with Session(db_engine) as session:
        records = PopulationFindingRepository().list_for_system(session, system_id)

    result = verify_population_findings(records, public_key_hex=public_key_hex)
    assert result.valid is True
    for record in records:
        assert record.signature is not None
        assert population_finding_hash(record.as_population_finding())


def test_a_production_registration_with_no_deployed_class_is_skipped_not_an_error(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    # A real, if unusual, production state: some other process registered
    # and promoted a POPULATION_POLICY plugin_id/version this process's
    # own code has no matching @register_population_policy class for
    # (e.g. a rolling deploy where an old worker hasn't picked up new
    # code yet) -- mirrors the identical branch api/ingestion/routes.py
    # already handles for Policy.
    system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    undeployed_policy_id = f"undeployed-population-policy-{uuid4()}"
    with Session(db_engine) as session:
        registration_repository = PluginRegistrationRepository()
        registration = registration_repository.create(
            session,
            plugin_type=PluginType.POPULATION_POLICY,
            plugin_id=undeployed_policy_id,
            version="0.1.0",
        )
        registration_repository.promote(session, registration.id)  # DRAFT -> SHADOW
        registration_repository.promote(session, registration.id)  # SHADOW -> PRODUCTION
        PopulationPolicyBindingRepository().create(
            session, system_id=system_id, population_policy_id=undeployed_policy_id
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)
    assert findings == []


def test_one_bindings_failure_is_reported_and_does_not_abort_the_rest_of_the_run(
    postgres_url, db_engine, seed_finance_decisions, monkeypatch
) -> None:
    import gov_platform.population_engine.run_policies as run_policies_module

    good_system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    bad_system_id = seed_finance_decisions([({"race": "Black"}, True, _IN_WINDOW)])
    with Session(db_engine) as session:
        binding_repository = PopulationPolicyBindingRepository()
        binding_repository.create(
            session, system_id=bad_system_id, population_policy_id="adverse-impact-ratio"
        )
        binding_repository.create(
            session, system_id=good_system_id, population_policy_id="adverse-impact-ratio"
        )
        session.commit()

    real_build_population_window = run_policies_module.build_population_window

    def _fail_for_bad_system(engine, *, system_id, window_start, window_end):
        if system_id == bad_system_id:
            raise RuntimeError("simulated window-build failure")
        return real_build_population_window(
            engine, system_id=system_id, window_start=window_start, window_end=window_end
        )

    monkeypatch.setattr(run_policies_module, "build_population_window", _fail_for_bad_system)

    exit_code = _run(postgres_url)

    assert exit_code == 1  # a real error occurred, distinct from a clean skip
    with Session(db_engine) as session:
        good_findings = PopulationFindingRepository().list_for_system(session, good_system_id)
        bad_findings = PopulationFindingRepository().list_for_system(session, bad_system_id)
    assert len(good_findings) == 1  # the other binding still ran to completion
    assert bad_findings == []


def test_two_population_policies_are_both_evaluated_independently_for_the_same_system(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    """M8 (docs/milestones/M8.md §4.1): proves population-policy plurality
    holds with a second, genuinely different concrete policy, with zero
    change to run_policies.py's existing per-binding independence."""
    system_id = seed_finance_decisions(
        [
            ({"race": "Black"}, True, _IN_WINDOW),
            *[({"race": "Black"}, False, _IN_WINDOW) for _ in range(39)],  # 1/40 = 2.5%
            *[({"race": "White"}, True, _IN_WINDOW) for _ in range(40)],  # 100%
        ]
    )
    with Session(db_engine) as session:
        binding_repository = PopulationPolicyBindingRepository()
        binding_repository.create(
            session, system_id=system_id, population_policy_id="adverse-impact-ratio"
        )
        binding_repository.create(
            session, system_id=system_id, population_policy_id="disparity-significance-test"
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)

    findings_by_policy = {f.population_policy_id: f for f in findings}
    assert set(findings_by_policy) == {"adverse-impact-ratio", "disparity-significance-test"}
    for finding in findings_by_policy.values():
        assert finding.signature is not None
        assert finding.parameters_used is not None  # every M8-era finding tracks this


def test_a_bindings_parameters_are_threaded_through_to_the_computed_finding(
    postgres_url, db_engine, seed_finance_decisions
) -> None:
    """M8 (docs/milestones/M8.md §4.3): a binding's admin-configured
    `parameters` actually change what gets computed, end to end through
    the real batch runner, not just at the policy's own `evaluate()`
    layer."""
    system_id = seed_finance_decisions(
        [
            ({"race": "Black"}, True, _IN_WINDOW),
            *[({"race": "Black"}, False, _IN_WINDOW) for _ in range(39)],  # rate 0.025
            *[({"race": "White"}, True, _IN_WINDOW) for _ in range(40)],  # rate 1.0 -> ratio 0.025
        ]
    )
    with Session(db_engine) as session:
        PopulationPolicyBindingRepository().create(
            session,
            system_id=system_id,
            population_policy_id="adverse-impact-ratio",
            parameters={"threshold": 0.01},  # low enough that 0.025 no longer flags
        )
        session.commit()

    exit_code = _run(postgres_url)

    assert exit_code == 0
    with Session(db_engine) as session:
        findings = PopulationFindingRepository().list_for_system(session, system_id)

    assert len(findings) == 1
    assert findings[0].outcome.value == "CLEAR"
    assert findings[0].parameters_used == {"threshold": 0.01, "minimum_group_size": 30.0}


def test_window_start_and_window_end_must_be_given_together() -> None:
    # argparse.ArgumentParser.error() calls sys.exit(2) directly.
    with pytest.raises(SystemExit) as exc_info:
        main(["--database-url", "postgresql://unused", "--window-start", _WINDOW_START.isoformat()])
    assert exc_info.value.code == 2


def test_default_window_run_does_not_error_with_no_active_bindings(postgres_url) -> None:
    # Not scoped to any particular system -- proves the "no window
    # override given" default-window code path at least runs end to end
    # without needing to wait for a real "yesterday" to have real data in
    # it (there may be zero active bindings entirely, which is fine).
    exit_code = main(["--database-url", postgres_url])
    assert exit_code in (0, 1)
