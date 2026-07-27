"""Protected Attribute Rules Admin API — architecture §4.3, M5.

Manages the DB-backed classification ruleset `EvidenceStore`'s resolution
path consults (see `protected_attributes/resolver.py`) — an
admin-configurable replacement for `classification.py`'s static rules for
that one consumer. No lifecycle to promote: a rule row simply exists or
doesn't, unlike a plugin registration or a policy binding (see
`docs/milestones/M5.md` §13.9 for why `DirectAttributeInInputsPolicy`'s own
copy is a deliberately separate, unaffected consumer).

Mirrors `api/admin/systems.py`'s shape (`POST`/`GET`/`GET by id`, no
lifecycle actions).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.api.dependencies import get_db_engine, get_protected_attribute_rule_repository
from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.schemas.protected_attribute_rule import ProtectedAttributeRuleClassification

router = APIRouter(tags=["admin"])


class ProtectedAttributeRuleRequest(BaseModel):
    domain: str
    attribute_name: str
    classification: ProtectedAttributeRuleClassification
    proxy_of: str | None = None


class ProtectedAttributeRuleResponse(BaseModel):
    id: str
    domain: str
    attribute_name: str
    classification: ProtectedAttributeRuleClassification
    proxy_of: str | None
    created_at: datetime


@router.post(
    "/protected-attribute-rules",
    response_model=ProtectedAttributeRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_protected_attribute_rule(
    payload: ProtectedAttributeRuleRequest,
    engine: Engine = Depends(get_db_engine),
    protected_attribute_rule_repository: ProtectedAttributeRuleRepository = Depends(
        get_protected_attribute_rule_repository
    ),
) -> ProtectedAttributeRuleResponse:
    with Session(engine) as session:
        existing = protected_attribute_rule_repository.get_by_identity(
            session, domain=payload.domain, attribute_name=payload.attribute_name
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"a protected attribute rule for domain {payload.domain!r} attribute "
                    f"{payload.attribute_name!r} already exists"
                ),
            )
        # ValueError (proxy_of/classification mismatch) propagates to the
        # app-wide handler in api/app.py, mapped to 422 -- same mechanism
        # every other domain-invariant violation in this codebase uses.
        rule = protected_attribute_rule_repository.create(
            session,
            domain=payload.domain,
            attribute_name=payload.attribute_name,
            classification=payload.classification,
            proxy_of=payload.proxy_of,
        )
        session.commit()

    return ProtectedAttributeRuleResponse(**rule.model_dump())


@router.get("/protected-attribute-rules", response_model=list[ProtectedAttributeRuleResponse])
def list_protected_attribute_rules(
    engine: Engine = Depends(get_db_engine),
    protected_attribute_rule_repository: ProtectedAttributeRuleRepository = Depends(
        get_protected_attribute_rule_repository
    ),
) -> list[ProtectedAttributeRuleResponse]:
    with Session(engine) as session:
        rules = protected_attribute_rule_repository.list_all(session)
    return [ProtectedAttributeRuleResponse(**r.model_dump()) for r in rules]


@router.get("/protected-attribute-rules/{rule_id}", response_model=ProtectedAttributeRuleResponse)
def get_protected_attribute_rule(
    rule_id: str,
    engine: Engine = Depends(get_db_engine),
    protected_attribute_rule_repository: ProtectedAttributeRuleRepository = Depends(
        get_protected_attribute_rule_repository
    ),
) -> ProtectedAttributeRuleResponse:
    with Session(engine) as session:
        rule = protected_attribute_rule_repository.get(session, rule_id)

    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="protected attribute rule not found"
        )
    return ProtectedAttributeRuleResponse(**rule.model_dump())
