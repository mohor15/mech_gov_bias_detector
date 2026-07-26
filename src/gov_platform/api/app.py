"""FastAPI application factory — the composition root.

This is the one place that knows about every concrete implementation
(`SyntheticAdapter`, `NormalizationService`, `AlwaysAllowPolicy`,
`GovernanceEngine`, `EvidenceStore`, the repositories) and wires them
together. Everything else in the codebase depends only on abstractions
(`Adapter`, `Policy`) or receives its collaborators through
`api.dependencies` — this is the Dependency Inversion half of that story,
and it is what makes `create_app(settings=...)` produce a fully isolated
instance per test rather than sharing V1's bare module-level globals.

M1: constructs one shared `Engine` (see `db.session`) and injects it into
both `EvidenceStore` and the Admin API's `SystemRepository` — connection-
pool sharing, not two isolated pools. Building the engine here does not
require a live database (SQLAlchemy engines are lazy) — see
`EvidenceStore`'s module docstring for why that matters.

M2: adds a second `Adapter` (`CreditScorecardAdapter`) and a second
`GovernanceEngine`, wired with the new `DirectAttributeInInputsPolicy`
rather than reusing the existing `AlwaysAllowPolicy`-backed one —
`GovernanceEngine` still takes exactly one `Policy` (M4 scope, unchanged),
so two independently-policied engines is the correct amount of generality
for two adapters with two different governance needs, not a widening of
that class. Both routes still share the *same* `EvidenceStore` — one
append-only ledger for the whole platform, not one per adapter. One
`ProtectedAttributeResolver` instance is shared between `EvidenceStore`
and the new policy: it is stateless (a pure function of its static
ruleset), so sharing it is a minor reuse, not a hidden coupling.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gov_platform.adapters.credit_scorecard import CreditScorecardAdapter
from gov_platform.adapters.synthetic import SyntheticAdapter
from gov_platform.api import health
from gov_platform.api.admin import systems as admin_systems
from gov_platform.api.ingestion import routes as ingestion
from gov_platform.api.middleware import MaxBodySizeMiddleware
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.config.settings import Settings, get_settings
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.session import create_db_engine
from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.normalization.service import NormalizationService
from gov_platform.observability.logging import configure_logging
from gov_platform.policy_engine.policies.always_allow import AlwaysAllowPolicy
from gov_platform.policy_engine.policies.direct_attribute_in_inputs import (
    DirectAttributeInInputsPolicy,
)
from gov_platform.protected_attributes.resolver import ProtectedAttributeResolver

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully-wired, independently instantiable application.

    Accepting an explicit `settings` override (rather than always reading
    the process-wide cached settings) is what lets integration tests point
    at an isolated database without touching environment variables.
    """
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.LOG_LEVEL)

    app = FastAPI(title=resolved_settings.APP_NAME, version=resolved_settings.VERSION)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=resolved_settings.MAX_REQUEST_BODY_BYTES)

    db_engine = create_db_engine(resolved_settings.DATABASE_URL)
    protected_attribute_resolver = ProtectedAttributeResolver()

    app.state.adapter = SyntheticAdapter()
    app.state.normalization_service = NormalizationService()
    app.state.governance_engine = GovernanceEngine(policy=AlwaysAllowPolicy())
    app.state.db_engine = db_engine
    app.state.evidence_store = EvidenceStore(db_engine, resolver=protected_attribute_resolver)
    app.state.system_repository = SystemRepository()

    app.state.credit_scorecard_adapter = CreditScorecardAdapter()
    app.state.credit_scorecard_governance_engine = GovernanceEngine(
        policy=DirectAttributeInInputsPolicy(resolver=protected_attribute_resolver)
    )

    app.include_router(health.router)
    app.include_router(ingestion.router, prefix="/v1/ingestion")
    app.include_router(admin_systems.router, prefix="/v1/admin")

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        # M2 production-readiness finding: ProtectedAttributeResolver raises
        # ValueError for a protected attribute its domain's ruleset doesn't
        # recognize (see protected_attributes/resolver.py). Reaching this
        # point means DirectAttributeInInputsPolicy.evaluate (or, more
        # rarely, EvidenceStore.append's own resolution step) rejected the
        # request's content -- structurally valid per Pydantic, but not
        # semantically acceptable. That is a client-correctable input
        # problem (422), the same category Pydantic's own automatic
        # validation errors fall into, not a server fault (500) — without
        # this handler it would fall through to the generic one below and
        # be misreported as one. Registered ahead of the generic handler by
        # specificity, not registration order (FastAPI dispatches by the
        # most specific matching exception type).
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # V1's FastAPI service had no handler here at all: an unexpected error
        # became a raw 500 with a stack trace sent straight to the client.
        # This logs the full exception server-side and returns nothing but a
        # generic message — a deliberate, minimal fix to that specific gap,
        # not a general-purpose error-handling framework.
        logger.exception("unhandled_exception", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    return app
