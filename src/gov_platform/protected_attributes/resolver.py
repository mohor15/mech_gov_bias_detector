"""The Protected Attribute Resolution Service — architecture §4.3, M2.

Classifies each of a Decision Event's supplied protected attributes as
`DIRECT` or `PROXIED` per a domain's ruleset, and emits a `WITHHELD`
resolution for every attribute the domain expects but the event didn't
supply.

A concrete service, not a port/ABC — unlike `Adapter`/`Policy`, this has
exactly one implementation and no second resolution strategy to justify
polymorphism. See `docs/milestones/M2.md` §7 for the full reasoning;
introducing a third plugin surface here ahead of a real second case would
repeat the "speculative generality" mistake M0/M1 have consistently
avoided elsewhere. Mirrors `NormalizationService`'s shape, not
`Adapter`/`Policy`'s.

Deliberately does not look up `System.domain` itself — callers supply it,
because they get it differently. `EvidenceStore` already has a live
`System` row mid-transaction and passes its real `domain`.
`DirectAttributeInInputsPolicy` has no database access at all (by design —
see its own docstring) and is instead constructed with a fixed domain
matching the one system/route it governs.

M5: the ruleset source is chosen once, at construction — the static,
in-code `classification.py` rules by default (zero-argument construction,
unchanged, still what `DirectAttributeInInputsPolicy` uses), or the
DB-backed `protected_attribute_rules` table when constructed with an
`Engine` (what `EvidenceStore` uses from M5 onward). This is a deliberate,
named divergence between the two consumers, not an oversight — giving a
zero-argument-constructed `Policy` database access would be a real `Policy`
port change this milestone does not make. See `docs/milestones/M5.md`
§13.9 for the full reasoning.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.protected_attributes.classification import (
    DomainProtectedAttributeRules,
    rules_for_domain,
)
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)


class ProtectedAttributeResolver:
    """Resolves one Decision Event's protected attributes for one domain."""

    def __init__(self, *, engine: Engine | None = None) -> None:
        self._engine = engine

    def _rules_for_domain(self, domain: str | None) -> DomainProtectedAttributeRules | None:
        if domain is None:
            return None
        if self._engine is None:
            return rules_for_domain(domain)

        # Local import: avoids a module-level cycle (this module has never
        # depended on `db` before M5; the DB-backed path is the one place
        # that needs to).
        from gov_platform.db.repositories.protected_attribute_rule import (
            ProtectedAttributeRuleRepository,
        )

        with Session(self._engine) as session:
            return ProtectedAttributeRuleRepository().rules_for_domain(session, domain)

    def resolve(
        self, event: DecisionEvent, *, domain: str | None
    ) -> list[ResolvedProtectedAttribute]:
        """Resolve `event`'s protected attributes against `domain`'s ruleset.

        Returns an empty list for a domain with no defined ruleset (see
        `classification.rules_for_domain`) — a `System` outside any domain
        this milestone governs is unaffected, not an error case.

        Raises `ValueError` if `event` supplies a protected attribute the
        domain's ruleset doesn't recognize at all (neither direct nor
        proxied). This is deliberately a hard failure, not a silent
        default: an unrecognized attribute reaching a *known* domain's
        resolution means the adapter and `classification.py` have drifted
        out of sync, which is exactly the kind of "no method exists for
        it" application-layer stopgap M1's evidence-immutability work
        rejected in favor of an enforced guarantee (see
        `docs/milestones/M2.md` §10).
        """
        rules = self._rules_for_domain(domain)
        if rules is None:
            return []

        supplied = set(event.protected_attribute_refs)
        unrecognized = supplied - rules.expected_attributes
        if unrecognized:
            raise ValueError(
                f"protected attribute(s) {sorted(unrecognized)} supplied for domain "
                f"{domain!r} have no classification rule"
            )

        resolved_at = datetime.now(UTC)
        resolutions: list[ResolvedProtectedAttribute] = []

        for attribute_name in sorted(rules.expected_attributes):
            if attribute_name not in supplied:
                resolutions.append(
                    ResolvedProtectedAttribute(
                        decision_event_id=event.event_id,
                        attribute_name=attribute_name,
                        classification=ProtectedAttributeClassification.WITHHELD,
                        resolved_at=resolved_at,
                    )
                )
            elif attribute_name in rules.direct_attributes:
                resolutions.append(
                    ResolvedProtectedAttribute(
                        decision_event_id=event.event_id,
                        attribute_name=attribute_name,
                        classification=ProtectedAttributeClassification.DIRECT,
                        resolved_at=resolved_at,
                    )
                )
            else:
                resolutions.append(
                    ResolvedProtectedAttribute(
                        decision_event_id=event.event_id,
                        attribute_name=attribute_name,
                        classification=ProtectedAttributeClassification.PROXIED,
                        proxy_basis=rules.proxy_attributes[attribute_name],
                        resolved_at=resolved_at,
                    )
                )

        return resolutions
