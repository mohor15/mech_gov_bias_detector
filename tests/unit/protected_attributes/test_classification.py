"""`rules_for_domain` — pure, no DB. Exercised indirectly through
`ProtectedAttributeResolver` too, but tested directly here for its own
public contract: `resolver.py`'s `_rules_for_domain` short-circuits on
`domain is None` before ever calling this function, so this module's own
`None` handling needs its own direct test to stay covered.
"""

from __future__ import annotations

from gov_platform.protected_attributes.classification import FINANCE, rules_for_domain


def test_none_domain_resolves_to_nothing() -> None:
    assert rules_for_domain(None) is None


def test_unknown_domain_resolves_to_nothing() -> None:
    assert rules_for_domain("HEALTHCARE") is None


def test_finance_domain_returns_its_ruleset() -> None:
    assert rules_for_domain("FINANCE") is FINANCE
