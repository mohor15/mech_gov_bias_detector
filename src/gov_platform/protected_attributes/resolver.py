"""The Protected Attribute Resolution Service — architecture §4.3, M2.

Classifies each of a Decision Event's supplied protected attributes as
`DIRECT` or `PROXIED` per the domain's static ruleset
(`classification.py`), and emits a `WITHHELD` resolution for every
attribute the domain expects but the event didn't supply.

A concrete service, not a port/ABC — unlike `Adapter`/`Policy`, this has
exactly one implementation and no second resolution strategy to justify
polymorphism. See `docs/milestones/M2.md` §7 for the full reasoning;
introducing a third plugin surface here ahead of a real second case would
repeat the "speculative generality" mistake M0/M1 have consistently
avoided elsewhere. Mirrors `NormalizationService`'s shape, not
`Adapter`/`Policy`'s.

Pure and DB-free: takes a `DecisionEvent` and a domain string, returns
`list[ResolvedProtectedAttribute]`. Deliberately does not look up
`System.domain` itself — callers supply it, because they get it
differently. `EvidenceStore` already has a live `System` row mid-transaction
and passes its real `domain`. `DirectAttributeInInputsPolicy` has no
database access at all (by design — see its own docstring) and is instead
constructed with a fixed domain matching the one system/route it governs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.protected_attributes.classification import rules_for_domain
from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)


class ProtectedAttributeResolver:
    """Resolves one Decision Event's protected attributes for one domain."""

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
        rules = rules_for_domain(domain)
        if rules is None:
            return []

        supplied = set(event.protected_attribute_refs)
        unrecognized = supplied - rules.expected_attributes
        if unrecognized:
            raise ValueError(
                f"protected attribute(s) {sorted(unrecognized)} supplied for domain "
                f"{domain!r} have no classification rule in "
                "protected_attributes/classification.py"
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
