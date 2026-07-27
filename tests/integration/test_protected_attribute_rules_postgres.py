"""`ProtectedAttributeRuleRepository` — real Postgres round trip, including
the `UNIQUE (domain, attribute_name)` database constraint (migration
`0012`) and the classification/proxy_of consistency check. CI-only (see
conftest.requires_postgres).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.schemas.protected_attribute_rule import ProtectedAttributeRuleClassification
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def _unique_domain() -> str:
    return f"test-domain-{uuid4()}"


def test_create_registers_a_direct_rule(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        rule = ProtectedAttributeRuleRepository().create(
            session,
            domain=_unique_domain(),
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )

    assert rule.classification is ProtectedAttributeRuleClassification.DIRECT
    assert rule.proxy_of is None


def test_create_a_proxy_rule_requires_proxy_of(db_engine: Engine) -> None:
    with Session(db_engine) as session, pytest.raises(ValueError, match="proxy_of is required"):
        ProtectedAttributeRuleRepository().create(
            session,
            domain=_unique_domain(),
            attribute_name="zip_code",
            classification=ProtectedAttributeRuleClassification.PROXY,
        )


def test_create_a_direct_rule_forbids_proxy_of(db_engine: Engine) -> None:
    with Session(db_engine) as session, pytest.raises(ValueError, match="must not be set"):
        ProtectedAttributeRuleRepository().create(
            session,
            domain=_unique_domain(),
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
            proxy_of="race",
        )


def test_get_returns_none_for_an_unknown_id(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        assert ProtectedAttributeRuleRepository().get(session, "no-such-id") is None


def test_get_by_identity_returns_none_for_an_unregistered_rule(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = ProtectedAttributeRuleRepository().get_by_identity(
            session, domain="does-not-exist", attribute_name="does-not-exist"
        )
    assert result is None


def test_list_for_domain_returns_only_that_domains_rules(db_engine: Engine) -> None:
    domain = _unique_domain()
    other_domain = _unique_domain()
    with Session(db_engine) as session:
        repository = ProtectedAttributeRuleRepository()
        repository.create(
            session,
            domain=domain,
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        repository.create(
            session,
            domain=other_domain,
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        session.commit()

        rules = repository.list_for_domain(session, domain)

    assert len(rules) == 1
    assert rules[0].domain == domain


def test_rules_for_domain_returns_none_for_a_domain_with_no_rows(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = ProtectedAttributeRuleRepository().rules_for_domain(session, "no-such-domain")
    assert result is None


def test_rules_for_domain_groups_direct_and_proxy_rows(db_engine: Engine) -> None:
    domain = _unique_domain()
    with Session(db_engine) as session:
        repository = ProtectedAttributeRuleRepository()
        repository.create(
            session,
            domain=domain,
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        repository.create(
            session,
            domain=domain,
            attribute_name="zip_code",
            classification=ProtectedAttributeRuleClassification.PROXY,
            proxy_of="race",
        )
        session.commit()

        rules = repository.rules_for_domain(session, domain)

    assert rules is not None
    assert rules.direct_attributes == frozenset({"race"})
    assert rules.proxy_attributes == {"zip_code": "race"}
    assert rules.expected_attributes == frozenset({"race", "zip_code"})


def test_create_raises_a_clean_error_for_a_duplicate_identity(db_engine: Engine) -> None:
    domain = _unique_domain()
    with Session(db_engine) as session:
        repository = ProtectedAttributeRuleRepository()
        repository.create(
            session,
            domain=domain,
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        session.commit()

        with pytest.raises(ValueError, match="already exists"):
            repository.create(
                session,
                domain=domain,
                attribute_name="race",
                classification=ProtectedAttributeRuleClassification.DIRECT,
            )


def test_list_all_includes_created_rules(db_engine: Engine) -> None:
    domain = _unique_domain()
    with Session(db_engine) as session:
        repository = ProtectedAttributeRuleRepository()
        created = repository.create(
            session,
            domain=domain,
            attribute_name="race",
            classification=ProtectedAttributeRuleClassification.DIRECT,
        )
        session.commit()

        all_rules = repository.list_all(session)

    assert created.id in {r.id for r in all_rules}
