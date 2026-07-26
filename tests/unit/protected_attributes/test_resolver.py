"""`ProtectedAttributeResolver` — pure logic, no DB. See
`protected_attributes/classification.py` for the FINANCE ruleset this
exercises: direct = {race, gender, age, marital_status}, proxies =
{zip_code -> race, first_name -> gender}.
"""

from __future__ import annotations

import pytest

from gov_platform.protected_attributes.resolver import ProtectedAttributeResolver
from gov_platform.schemas.protected_attribute import ProtectedAttributeClassification


def test_domain_with_no_ruleset_resolves_to_nothing(make_decision_event) -> None:
    # None is the common case (M0/M1's synthetic-scorecard system never
    # registers a domain) -- must be a no-op, not an error.
    event = make_decision_event(protected_attribute_refs={"country": "India"})

    assert ProtectedAttributeResolver().resolve(event, domain=None) == []


def test_unknown_domain_string_also_resolves_to_nothing(make_decision_event) -> None:
    event = make_decision_event(protected_attribute_refs={"country": "India"})

    assert ProtectedAttributeResolver().resolve(event, domain="HEALTHCARE") == []


def test_finance_domain_classifies_direct_proxied_and_withheld(make_decision_event) -> None:
    event = make_decision_event(
        protected_attribute_refs={"race": "Black", "zip_code": "12345"}
    )

    resolutions = ProtectedAttributeResolver().resolve(event, domain="FINANCE")

    by_attribute = {r.attribute_name: r for r in resolutions}
    assert set(by_attribute) == {
        "age",
        "first_name",
        "gender",
        "marital_status",
        "race",
        "zip_code",
    }

    assert by_attribute["race"].classification is ProtectedAttributeClassification.DIRECT
    assert by_attribute["race"].proxy_basis is None

    assert by_attribute["zip_code"].classification is ProtectedAttributeClassification.PROXIED
    assert by_attribute["zip_code"].proxy_basis == "race"

    for missing in ("age", "first_name", "gender", "marital_status"):
        assert by_attribute[missing].classification is ProtectedAttributeClassification.WITHHELD
        assert by_attribute[missing].proxy_basis is None


def test_every_resolution_is_stamped_with_the_decision_event_id(make_decision_event) -> None:
    event = make_decision_event(event_id="evt-xyz", protected_attribute_refs={"race": "Asian"})

    resolutions = ProtectedAttributeResolver().resolve(event, domain="FINANCE")

    assert resolutions  # sanity: FINANCE always has expected attributes
    assert all(r.decision_event_id == "evt-xyz" for r in resolutions)
    assert all(r.resolved_at.tzinfo is not None for r in resolutions)


def test_fully_withheld_event_produces_a_withheld_row_for_every_expected_attribute(
    make_decision_event,
) -> None:
    event = make_decision_event(protected_attribute_refs={})

    resolutions = ProtectedAttributeResolver().resolve(event, domain="FINANCE")

    assert len(resolutions) == 6
    assert all(
        r.classification is ProtectedAttributeClassification.WITHHELD for r in resolutions
    )


def test_unrecognized_attribute_for_a_known_domain_raises(make_decision_event) -> None:
    # A FINANCE-domain event supplying an attribute FINANCE's ruleset has
    # no rule for at all signals the adapter and classification.py have
    # drifted out of sync -- must fail loudly, not silently ignore it.
    event = make_decision_event(protected_attribute_refs={"country": "India"})

    with pytest.raises(ValueError, match="country"):
        ProtectedAttributeResolver().resolve(event, domain="FINANCE")
