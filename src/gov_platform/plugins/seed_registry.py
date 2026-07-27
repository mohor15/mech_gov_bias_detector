"""CLI: idempotently register every first-party plugin `plugins.bootstrap`
knows about and promote each straight to `PRODUCTION` — architecture §6,
M3. M5: also seeds the equivalent Policy Bindings and `FINANCE` protected-
attribute rules the two first-party adapters relied on as static, code-
defined facts through M4.

Not something `create_app()` does itself: `create_app()` must stay
DB-free at construction time (an invariant every milestone since M0 has
preserved — see `api/app.py`'s module docstring), so seeding the registry
is a separate, explicit ops step, the same relationship `db.migrate` has
to schema. Run once after applying migrations, before the app is expected
to serve real ingestion traffic. Safe to re-run: an already-`PRODUCTION`
registration, an already-existing binding, or an already-existing rule is
left alone, not re-created or duplicated.

M5's seed data (`_FIRST_PARTY_POLICY_BINDINGS`, `_FINANCE_PROTECTED_ATTRIBUTE_RULES`)
is exactly what `Adapter.governing_policy_ids` (M3/M4) and
`classification.py`'s static `_RULES_BY_DOMAIN` (M2) encoded in code —
this is a pure storage-location migration, not a behavior change, so a
fresh cutover reproduces M0-M4 behavior exactly.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.db.session import create_db_engine
from gov_platform.plugins.bootstrap import bootstrap_plugins
from gov_platform.plugins.registry import known_adapter_keys, known_policy_keys
from gov_platform.protected_attributes.classification import FINANCE, FINANCE_DOMAIN
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType
from gov_platform.schemas.policy_binding import PolicySeverity
from gov_platform.schemas.protected_attribute_rule import ProtectedAttributeRuleClassification

# The M3/M4 static Adapter.governing_policy_ids tuples, reproduced here as
# the initial database facts -- see docs/milestones/M5.md §13.1/§13.13.
# Severity is a fresh M5 judgment (no prior milestone assigned one): the
# fairness gate is HIGH (a direct protected-attribute leak into model
# inputs is a real fair-lending violation -> RECOMMEND_HOLD), the risk
# gate is MEDIUM (a debt-ratio flag warrants review, not an automatic
# hold -> ESCALATE_FOR_REVIEW), and the always-allow synthetic path is LOW
# (it can never actually flag).
_FIRST_PARTY_POLICY_BINDINGS: dict[str, list[tuple[str, PolicySeverity]]] = {
    "synthetic": [("always-allow", PolicySeverity.LOW)],
    "credit-scorecard": [
        ("direct-attribute-in-inputs", PolicySeverity.HIGH),
        ("high-debt-ratio-gate", PolicySeverity.MEDIUM),
    ],
}


def seed_to_production(
    session: Session,
    repository: PluginRegistrationRepository,
    *,
    plugin_type: PluginType,
    plugin_id: str,
    version: str,
) -> str:
    """Ensure `(plugin_type, plugin_id, version)` is registered and at
    `PRODUCTION`. Returns a short, human-readable status line."""
    registration = repository.get_by_identity(
        session, plugin_type=plugin_type, plugin_id=plugin_id, version=version
    )
    if registration is None:
        registration = repository.create(
            session, plugin_type=plugin_type, plugin_id=plugin_id, version=version
        )

    # Captured as a plain bool, not an early `return`: an early return here
    # would let mypy narrow `registration.lifecycle_state`'s type to
    # exclude PRODUCTION for the rest of this function, making the loop
    # condition below look like an always-true comparison to it -- even
    # though `registration` is reassigned every iteration to a fresh
    # object whose state genuinely can reach PRODUCTION.
    was_already_production = registration.lifecycle_state is PluginLifecycleState.PRODUCTION

    while registration.lifecycle_state is not PluginLifecycleState.PRODUCTION:
        registration = repository.promote(session, registration.id)

    if was_already_production:
        return f"{plugin_type.value} {plugin_id} {version}: already PRODUCTION"
    return f"{plugin_type.value} {plugin_id} {version}: promoted to PRODUCTION"


def seed_policy_binding(
    session: Session,
    repository: PolicyBindingRepository,
    *,
    adapter_id: str,
    policy_id: str,
    severity: PolicySeverity,
) -> str:
    """Ensure a binding for `(adapter_id, policy_id)` exists. Idempotent:
    an existing binding is left exactly as it is, even if its severity
    differs from the seed default here -- an admin's deliberate severity
    change must never be silently reverted by re-running this seed."""
    existing = repository.get_by_identity(session, adapter_id=adapter_id, policy_id=policy_id)
    if existing is not None:
        return f"BINDING {adapter_id} -> {policy_id}: already exists"
    repository.create(session, adapter_id=adapter_id, policy_id=policy_id, severity=severity)
    return f"BINDING {adapter_id} -> {policy_id}: created (severity={severity.value})"


def seed_first_party_policy_bindings(
    session: Session, repository: PolicyBindingRepository
) -> list[str]:
    return [
        seed_policy_binding(
            session, repository, adapter_id=adapter_id, policy_id=policy_id, severity=severity
        )
        for adapter_id, bindings in sorted(_FIRST_PARTY_POLICY_BINDINGS.items())
        for policy_id, severity in bindings
    ]


def seed_protected_attribute_rule(
    session: Session,
    repository: ProtectedAttributeRuleRepository,
    *,
    domain: str,
    attribute_name: str,
    classification: ProtectedAttributeRuleClassification,
    proxy_of: str | None = None,
) -> str:
    """Ensure a rule for `(domain, attribute_name)` exists. Idempotent, same
    reasoning as `seed_policy_binding`."""
    existing = repository.get_by_identity(session, domain=domain, attribute_name=attribute_name)
    if existing is not None:
        return f"RULE {domain} {attribute_name}: already exists"
    repository.create(
        session,
        domain=domain,
        attribute_name=attribute_name,
        classification=classification,
        proxy_of=proxy_of,
    )
    return f"RULE {domain} {attribute_name}: created ({classification.value})"


def seed_finance_protected_attribute_rules(
    session: Session, repository: ProtectedAttributeRuleRepository
) -> list[str]:
    """Reproduces `classification.py`'s static `FINANCE` ruleset as
    database rows -- what `EvidenceStore`'s now-DB-backed resolution path
    consults from M5 onward (see `docs/milestones/M5.md` §13.13)."""
    results = [
        seed_protected_attribute_rule(
            session,
            repository,
            domain=FINANCE_DOMAIN,
            attribute_name=name,
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        for name in sorted(FINANCE.direct_attributes)
    ]
    results += [
        seed_protected_attribute_rule(
            session,
            repository,
            domain=FINANCE_DOMAIN,
            attribute_name=name,
            classification=ProtectedAttributeRuleClassification.PROXY,
            proxy_of=proxy_of,
        )
        for name, proxy_of in sorted(FINANCE.proxy_attributes.items())
    ]
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the plugin registry to PRODUCTION.")
    parser.add_argument("--database-url", required=True, help="The app's own runtime connection")
    args = parser.parse_args(argv)

    bootstrap_plugins()
    engine = create_db_engine(args.database_url)
    plugin_repository = PluginRegistrationRepository()
    policy_binding_repository = PolicyBindingRepository()
    protected_attribute_rule_repository = ProtectedAttributeRuleRepository()

    with Session(engine) as session:
        results = [
            seed_to_production(
                session,
                plugin_repository,
                plugin_type=PluginType.ADAPTER,
                plugin_id=plugin_id,
                version=version,
            )
            for plugin_id, version in sorted(known_adapter_keys())
        ]
        results += [
            seed_to_production(
                session,
                plugin_repository,
                plugin_type=PluginType.POLICY,
                plugin_id=plugin_id,
                version=version,
            )
            for plugin_id, version in sorted(known_policy_keys())
        ]
        results += seed_first_party_policy_bindings(session, policy_binding_repository)
        results += seed_finance_protected_attribute_rules(
            session, protected_attribute_rule_repository
        )
        session.commit()

    for line in results:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
