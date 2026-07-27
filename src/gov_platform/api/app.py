"""FastAPI application factory — the composition root.

This is the one place that knows about every concrete implementation
(`NormalizationService`, `EvidenceStore`, the repositories) and wires them
together. Everything else in the codebase depends only on abstractions
(`Adapter`, `Policy`) or receives its collaborators through
`api.dependencies` — this is the Dependency Inversion half of that story,
and it is what makes `create_app(settings=...)` produce a fully isolated
instance per test rather than sharing V1's bare module-level globals.

M1: constructs one shared `Engine` (see `db.session`) and injects it into
`EvidenceStore` and the Admin API's repositories — connection-pool
sharing, not several isolated pools. Building the engine here does not
require a live database (SQLAlchemy engines are lazy) — see
`EvidenceStore`'s module docstring for why that matters.

M3: **no longer hand-wires adapters or `GovernanceEngine`s here at all.**
M2 hardcoded two adapter/policy pairs directly in this function, naming it
explicitly as a stopgap ("real registry-based dispatch is M3 scope"). This
function now calls `plugins.bootstrap.bootstrap_plugins()` — an ordinary,
DB-free import side effect — and hands the resulting in-process registry
to `api.ingestion.routes.build_ingestion_router()`, which generates one
real route per registered adapter (see that module's docstring for how,
and for why route generation stays DB-free while per-request dispatch
resolves the actual governing policy from the database on every request).
One `ProtectedAttributeResolver`-equivalent concern from M2 doesn't apply
here the same way: each generated route's handler instantiates its own
policy per request from the registry, so there is no shared engine
instance to construct up front at all.

M5: two more repositories are constructed here (`PolicyBindingRepository`,
`ProtectedAttributeRuleRepository`) and two more Admin API routers wired in
— see `docs/milestones/M5.md`. Neither needs a live database at
construction time either, for the same reason every other repository here
doesn't: they hold no connection, only an `Engine`/`Session` passed in per
call.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gov_platform.api import health
from gov_platform.api.admin import plugins as admin_plugins
from gov_platform.api.admin import policy_bindings as admin_policy_bindings
from gov_platform.api.admin import protected_attribute_rules as admin_protected_attribute_rules
from gov_platform.api.admin import systems as admin_systems
from gov_platform.api.ingestion.routes import build_ingestion_router
from gov_platform.api.middleware import MaxBodySizeMiddleware
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.audit.signing import load_signer
from gov_platform.config.settings import Settings, get_settings
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.session import create_db_engine
from gov_platform.normalization.service import NormalizationService
from gov_platform.observability.logging import configure_logging
from gov_platform.plugins.bootstrap import bootstrap_plugins
from gov_platform.plugins.sandbox import PluginTimeoutError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully-wired, independently instantiable application.

    Accepting an explicit `settings` override (rather than always reading
    the process-wide cached settings) is what lets integration tests point
    at an isolated database without touching environment variables.
    """
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.LOG_LEVEL)
    bootstrap_plugins()

    app = FastAPI(title=resolved_settings.APP_NAME, version=resolved_settings.VERSION)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=resolved_settings.MAX_REQUEST_BODY_BYTES)

    db_engine = create_db_engine(resolved_settings.DATABASE_URL)
    signer = load_signer(
        resolved_settings.SIGNING_PRIVATE_KEY, key_id=resolved_settings.SIGNING_KEY_ID
    )

    app.state.normalization_service = NormalizationService()
    app.state.db_engine = db_engine
    app.state.evidence_store = EvidenceStore(db_engine, signer=signer)
    app.state.system_repository = SystemRepository()
    app.state.plugin_registration_repository = PluginRegistrationRepository()
    app.state.shadow_finding_repository = ShadowFindingRepository()
    app.state.policy_binding_repository = PolicyBindingRepository()
    app.state.protected_attribute_rule_repository = ProtectedAttributeRuleRepository()

    app.include_router(health.router)
    app.include_router(build_ingestion_router(), prefix="/v1/ingestion")
    app.include_router(admin_systems.router, prefix="/v1/admin")
    app.include_router(admin_plugins.router, prefix="/v1/admin")
    app.include_router(admin_policy_bindings.router, prefix="/v1/admin")
    app.include_router(admin_protected_attribute_rules.router, prefix="/v1/admin")

    @app.exception_handler(PluginTimeoutError)
    async def plugin_timeout_handler(request: Request, exc: PluginTimeoutError) -> JSONResponse:
        # M3: a plugin (Adapter.translate or Policy.evaluate) exceeded its
        # sandboxed execution budget (see plugins/sandbox.py). 504, not
        # 500: the platform itself is fine, a downstream step didn't
        # finish in time -- the same distinction a reverse proxy timeout
        # would draw.
        logger.error(
            "plugin_timeout", extra={"extra_fields": {"path": request.url.path, "detail": str(exc)}}
        )
        return JSONResponse(status_code=504, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        # M2 production-readiness finding: ProtectedAttributeResolver raises
        # ValueError for a protected attribute its domain's ruleset doesn't
        # recognize (see protected_attributes/resolver.py), and (M3)
        # PluginRegistrationRepository.promote raises it for an invalid
        # lifecycle transition. Both are client-correctable input problems
        # (422), the same category Pydantic's own automatic validation
        # errors fall into, not a server fault (500) — without this handler
        # they would fall through to the generic one below and be
        # misreported as one. Registered ahead of the generic handler by
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
