"""Repository for M5's DB-backed protected-attribute classification rules
— architecture §4.3.

`rules_for_domain` is the method `ProtectedAttributeResolver`'s DB-backed
mode actually depends on: it returns the same
`DomainProtectedAttributeRules` shape `protected_attributes/classification.py`
already defines for the static ruleset, built by grouping this domain's
rows -- reusing that existing dataclass rather than inventing a parallel
one, since the two are structurally identical.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import ProtectedAttributeRuleRow
from gov_platform.protected_attributes.classification import DomainProtectedAttributeRules
from gov_platform.schemas.protected_attribute_rule import (
    ProtectedAttributeRule,
    ProtectedAttributeRuleClassification,
)


class ProtectedAttributeRuleRepository:
    def create(
        self,
        session: Session,
        *,
        domain: str,
        attribute_name: str,
        classification: ProtectedAttributeRuleClassification,
        proxy_of: str | None = None,
    ) -> ProtectedAttributeRule:
        """Raises `ValueError` (mapped to a 422, same mechanism every other
        domain-invariant violation in this codebase uses) if `proxy_of` is
        inconsistent with `classification`: required for `PROXY`, forbidden
        for `DIRECT` -- mirrors `ResolvedProtectedAttribute.proxy_basis`'s
        own "set iff PROXIED" invariant."""
        if classification is ProtectedAttributeRuleClassification.PROXY and proxy_of is None:
            raise ValueError("proxy_of is required when classification is PROXY")
        if classification is ProtectedAttributeRuleClassification.DIRECT and proxy_of is not None:
            raise ValueError("proxy_of must not be set when classification is DIRECT")

        row = ProtectedAttributeRuleRow(
            id=str(uuid4()),
            domain=domain,
            attribute_name=attribute_name,
            classification=classification.value,
            proxy_of=proxy_of,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"a protected attribute rule for domain {domain!r} attribute "
                f"{attribute_name!r} already exists"
            ) from exc
        return self._to_model(row)

    def get(self, session: Session, rule_id: str) -> ProtectedAttributeRule | None:
        row = session.get(ProtectedAttributeRuleRow, rule_id)
        return self._to_model(row) if row is not None else None

    def get_by_identity(
        self, session: Session, *, domain: str, attribute_name: str
    ) -> ProtectedAttributeRule | None:
        row = session.execute(
            select(ProtectedAttributeRuleRow).where(
                ProtectedAttributeRuleRow.domain == domain,
                ProtectedAttributeRuleRow.attribute_name == attribute_name,
            )
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def list_all(self, session: Session) -> list[ProtectedAttributeRule]:
        rows = session.execute(
            select(ProtectedAttributeRuleRow).order_by(ProtectedAttributeRuleRow.created_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_for_domain(self, session: Session, domain: str) -> list[ProtectedAttributeRule]:
        rows = session.execute(
            select(ProtectedAttributeRuleRow).where(ProtectedAttributeRuleRow.domain == domain)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def rules_for_domain(
        self, session: Session, domain: str
    ) -> DomainProtectedAttributeRules | None:
        """`None` if `domain` has no rule rows at all -- the same "nothing
        to resolve" meaning `classification.rules_for_domain` gives an
        unrecognized domain, not an error."""
        rules = self.list_for_domain(session, domain)
        if not rules:
            return None

        direct_attributes = frozenset(
            r.attribute_name
            for r in rules
            if r.classification is ProtectedAttributeRuleClassification.DIRECT
        )
        proxy_attributes = {
            r.attribute_name: r.proxy_of
            for r in rules
            if r.classification is ProtectedAttributeRuleClassification.PROXY
            # r.proxy_of is guaranteed set for PROXY rows -- enforced at
            # create() time above.
            and r.proxy_of is not None
        }
        return DomainProtectedAttributeRules(
            direct_attributes=direct_attributes, proxy_attributes=proxy_attributes
        )

    @staticmethod
    def _to_model(row: ProtectedAttributeRuleRow) -> ProtectedAttributeRule:
        return ProtectedAttributeRule(
            id=row.id,
            domain=row.domain,
            attribute_name=row.attribute_name,
            classification=ProtectedAttributeRuleClassification(row.classification),
            proxy_of=row.proxy_of,
            created_at=row.created_at,
        )
