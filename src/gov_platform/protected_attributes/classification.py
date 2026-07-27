"""Static, code-defined protected-attribute classification rules — M2.

Not admin-configurable data itself — a deliberate M2 scope decision (see
`docs/milestones/M2.md` §11.5) that this module still honors. M5 added a
DB-backed, admin-configurable alternative (`protected_attribute_rules`,
consulted via `protected_attributes/resolver.py`'s optional `Engine` mode)
for `EvidenceStore`'s resolution path specifically — but
`DirectAttributeInInputsPolicy` deliberately still reads these static
rules directly, a named, temporary divergence (see
`docs/milestones/M5.md` §13.9), not an oversight. This module itself,
and the rules it defines, remain unchanged by M5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainProtectedAttributeRules:
    """One domain's protected-attribute vocabulary.

    ``direct_attributes`` are attribute names the domain treats as
    protected characteristics themselves (e.g. ``race``).
    ``proxy_attributes`` maps an attribute name to the direct attribute
    it's a known proxy for (e.g. ``zip_code`` -> ``race``).
    ``expected_attributes`` — every attribute name this domain has a rule
    for — is what `ProtectedAttributeResolver` checks a Decision Event's
    supplied attributes against to detect a missing (``WITHHELD``) one.
    """

    direct_attributes: frozenset[str]
    proxy_attributes: dict[str, str]

    @property
    def expected_attributes(self) -> frozenset[str]:
        return self.direct_attributes | frozenset(self.proxy_attributes)


# The one domain this milestone's real adapter targets, and the only key
# `_RULES_BY_DOMAIN` recognizes. Exported so callers that need to construct
# something *for* this domain specifically (e.g.
# `DirectAttributeInInputsPolicy`, fixed to this one domain per
# `docs/milestones/M2.md` §7) reference the same constant `System.domain`
# is matched against here, rather than duplicating the literal string.
FINANCE_DOMAIN = "FINANCE"

# Fair-lending protected characteristics (ECOA-inspired: race, sex, age,
# marital status) and the proxies most commonly cited in fair-lending
# analysis literature (zip code as a race proxy; given name as a gender
# proxy). Scoped to exactly the one domain this milestone's real adapter
# targets — extending to further domains without a second one to validate
# against would be speculative.
FINANCE = DomainProtectedAttributeRules(
    direct_attributes=frozenset({"race", "gender", "age", "marital_status"}),
    proxy_attributes={
        "zip_code": "race",
        "first_name": "gender",
    },
)

_RULES_BY_DOMAIN: dict[str, DomainProtectedAttributeRules] = {
    FINANCE_DOMAIN: FINANCE,
}


def rules_for_domain(domain: str | None) -> DomainProtectedAttributeRules | None:
    """The ruleset for `domain`, or `None` if this domain has no rules
    defined.

    `None` is a legitimate, common case — e.g. M0/M1's synthetic-scorecard
    system registers no `domain` at all — and is treated as "nothing to
    resolve," not an error, so ingestion for systems outside a domain this
    milestone actually governs is completely unaffected.

    Matching is case-sensitive and exact (`System.domain` is free text, no
    normalization applied anywhere in the schema) — a `System` registered
    with `domain="finance"` matches nothing here. Known limitation, not
    fixed in M2: normalizing domain names would be speculative without a
    second real domain to learn the right normalization rule from.
    """
    if domain is None:
        return None
    return _RULES_BY_DOMAIN.get(domain)
