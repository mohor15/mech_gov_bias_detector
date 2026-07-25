"""FastAPI application factory — the composition root.

This is the one place in M0 that knows about every concrete implementation
(`SyntheticAdapter`, `NormalizationService`, `AlwaysAllowPolicy`,
`GovernanceEngine`, `EvidenceStore`) and wires them together. Everything
else in the codebase depends only on abstractions (`Adapter`, `Policy`) or
receives its collaborators through `api.dependencies` — this is the
Dependency Inversion half of that story, and it is what makes
`create_app(settings=...)` produce a fully isolated instance per test
rather than sharing V1's bare module-level globals.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gov_platform.adapters.synthetic import SyntheticAdapter
from gov_platform.api import health
from gov_platform.api.ingestion import routes as ingestion
from gov_platform.api.middleware import MaxBodySizeMiddleware
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.config.settings import Settings, get_settings
from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.normalization.service import NormalizationService
from gov_platform.observability.logging import configure_logging
from gov_platform.policy_engine.policies.always_allow import AlwaysAllowPolicy

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully-wired, independently instantiable application.

    Accepting an explicit `settings` override (rather than always reading
    the process-wide cached settings) is what lets integration tests point
    the Evidence Store at a temp-directory SQLite file without touching
    environment variables.
    """
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.LOG_LEVEL)

    app = FastAPI(title=resolved_settings.APP_NAME, version=resolved_settings.VERSION)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=resolved_settings.MAX_REQUEST_BODY_BYTES)

    app.state.adapter = SyntheticAdapter()
    app.state.normalization_service = NormalizationService()
    app.state.governance_engine = GovernanceEngine(policy=AlwaysAllowPolicy())
    app.state.evidence_store = EvidenceStore(resolved_settings.EVIDENCE_DB_PATH)

    app.include_router(health.router)
    app.include_router(ingestion.router, prefix="/v1/ingestion")

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
