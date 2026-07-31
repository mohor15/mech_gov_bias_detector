"""FastAPI dependency providers.

Route handlers depend on these functions, never on concrete singletons
imported at module scope — this is what makes `api.app.create_app` a real
composition root and lets tests override any collaborator (e.g. pointing
the Evidence Store at a temp file) without monkeypatching module globals,
the trap V1 fell into with its bare module-level `pipeline = MechGovPipeline()`.

`NormalizationService` and `EvidenceStore` stay typed as concrete classes
deliberately: the architecture never defines them as swappable plugin
surfaces (only `Adapter` and `Policy` are ports), so introducing an
abstraction for them here would be speculative, not a fix.

M3 removes `get_adapter`/`get_credit_scorecard_adapter`/
`get_governance_engine`/`get_credit_scorecard_governance_engine` — M2's
per-adapter providers are obsolete now that ingestion routes are generated
from the plugin registry (see `api/ingestion/routes.py`): each generated
route's handler closes directly over its own adapter instance and resolves
its governing policy per-request from the database, rather than going
through a named provider function per adapter (there would need to be one
such function per registered adapter, which is exactly the "modifying the
composition root for every new adapter" problem M3 exists to remove).
`get_plugin_registration_repository` and `get_shadow_finding_repository`
are new — needed by both the Admin Plugins API and the generated ingestion
routes' per-request policy-lifecycle lookups.

M5: `get_policy_binding_repository` and `get_protected_attribute_rule_repository`
are new — needed by the new Admin API surfaces and (the former) by the
generated ingestion routes' per-request policy resolution.

M6: `get_population_policy_binding_repository` and
`get_population_finding_repository` are new — needed by the two new Admin
API surfaces (`population_engine/run_policies.py`'s batch job constructs
its own repositories directly, the same way `plugins/seed_registry.py`
always has, rather than going through this FastAPI-specific module).
`get_system_repository` (M1) is now also used by the Population Policy
Bindings Admin API, to validate `system_id` before creating a binding.

M9: `get_verdict_repository`, `get_verdict_review_repository`, and
`get_population_finding_review_repository` are new — needed by the two new
Human Review Workflow Admin API surfaces
(`api/admin/verdict_reviews.py`/`api/admin/population_finding_reviews.py`).
`get_verdict_repository` is new even though `VerdictRepository` itself
isn't (`EvidenceStore` has always constructed its own internally) — this is
the first Admin API surface that needs to *read* a `Verdict` at all, and
`audit/evidence_store.py`'s own `_queue_verdict_review` constructs its own
`VerdictReviewRepository` directly rather than through this module, the
same way `population_engine/run_policies.py` always has for its own
`PopulationFindingReviewRepository`.

M13: `get_auth_enabled`/`get_principal_repository` are new, plus the two
FastAPI dependency functions every authenticated route uses,
`get_current_principal`/`require_role` (see
`docs/milestones/M13.md` §5.2). `get_auth_enabled` reads a plain `bool`
off `app.state` (set once, in `create_app()`, from
`Settings.AUTH_ENABLED`) — the same narrow, purpose-built `app.state`
entry + matching provider-function shape every other collaborator here
already uses, not the whole `Settings` object. `AuthenticationError`/
`AuthorizationError` are defined here, alongside the dependencies that
raise them, mirroring `plugins/sandbox.PluginTimeoutError`'s own
"defined next to what raises it, imported by `api/app.py` for its
exception handler" precedent.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.access.tokens import hash_token
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.repositories.principal import PrincipalRepository
from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.db.repositories.verdict import VerdictRepository
from gov_platform.db.repositories.verdict_review import VerdictReviewRepository
from gov_platform.normalization.service import NormalizationService
from gov_platform.schemas.principal import Principal, PrincipalRole


class AuthenticationError(Exception):
    """Raised by `get_current_principal`: missing, malformed, unknown, or
    revoked credential."""


class AuthorizationError(Exception):
    """Raised by `require_role`: a real, known principal whose role
    doesn't permit this action."""


def get_normalization_service(request: Request) -> NormalizationService:
    service: NormalizationService = request.app.state.normalization_service
    return service


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


def get_db_engine(request: Request) -> Engine:
    """The one shared Engine, used directly by routes that need their own
    short-lived Session distinct from EvidenceStore's internal one — see
    api.app for why this is a single shared engine."""
    engine: Engine = request.app.state.db_engine
    return engine


def get_system_repository(request: Request) -> SystemRepository:
    repository: SystemRepository = request.app.state.system_repository
    return repository


def get_plugin_registration_repository(request: Request) -> PluginRegistrationRepository:
    repository: PluginRegistrationRepository = request.app.state.plugin_registration_repository
    return repository


def get_shadow_finding_repository(request: Request) -> ShadowFindingRepository:
    repository: ShadowFindingRepository = request.app.state.shadow_finding_repository
    return repository


def get_policy_binding_repository(request: Request) -> PolicyBindingRepository:
    repository: PolicyBindingRepository = request.app.state.policy_binding_repository
    return repository


def get_protected_attribute_rule_repository(
    request: Request,
) -> ProtectedAttributeRuleRepository:
    repository: ProtectedAttributeRuleRepository = (
        request.app.state.protected_attribute_rule_repository
    )
    return repository


def get_population_policy_binding_repository(
    request: Request,
) -> PopulationPolicyBindingRepository:
    repository: PopulationPolicyBindingRepository = (
        request.app.state.population_policy_binding_repository
    )
    return repository


def get_population_finding_repository(request: Request) -> PopulationFindingRepository:
    repository: PopulationFindingRepository = request.app.state.population_finding_repository
    return repository


def get_verdict_repository(request: Request) -> VerdictRepository:
    repository: VerdictRepository = request.app.state.verdict_repository
    return repository


def get_verdict_review_repository(request: Request) -> VerdictReviewRepository:
    repository: VerdictReviewRepository = request.app.state.verdict_review_repository
    return repository


def get_population_finding_review_repository(
    request: Request,
) -> PopulationFindingReviewRepository:
    repository: PopulationFindingReviewRepository = (
        request.app.state.population_finding_review_repository
    )
    return repository


def get_auth_enabled(request: Request) -> bool:
    enabled: bool = request.app.state.auth_enabled
    return enabled


def get_principal_repository(request: Request) -> PrincipalRepository:
    repository: PrincipalRepository = request.app.state.principal_repository
    return repository


def _extract_token(request: Request) -> str | None:
    """Checks, in order: the `Authorization: Bearer <token>` header (every
    API/CLI-style caller), then the `gov_platform_session` cookie (the
    dashboard, see `api/auth.py`) -- header takes precedence when both are
    present."""
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _separator, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token
    return request.cookies.get("gov_platform_session")


def resolve_principal_from_token(
    session: Session, principal_repository: PrincipalRepository, token: str
) -> Principal | None:
    """Given a raw bearer token, returns the matching `Principal`, or
    `None` if it doesn't match any principal or matches a revoked one --
    never raises. The one shared primitive both `get_current_principal`
    (token sourced from a header/cookie) and `api/auth.py`'s login
    endpoint (token sourced from the request body) build on."""
    principal = principal_repository.get_by_token_hash(session, hash_token(token))
    if principal is None or principal.revoked_at is not None:
        return None
    return principal


async def get_current_principal(
    request: Request,
    db_engine: Engine = Depends(get_db_engine),
    principal_repository: PrincipalRepository = Depends(get_principal_repository),
) -> Principal:
    """Raises `AuthenticationError` if no credential is present, the
    credential doesn't match any principal, or the matching principal is
    revoked. Never itself checks `AUTH_ENABLED` -- `require_role` (the
    only thing this codebase ever wires onto a route, per
    `docs/milestones/M13.md` §5.4) is the one place that short-circuits
    when authentication is disabled."""
    token = _extract_token(request)
    if token is None:
        raise AuthenticationError("missing credential")
    with Session(db_engine) as session:
        principal = resolve_principal_from_token(session, principal_repository, token)
    if principal is None:
        raise AuthenticationError("invalid or revoked credential")
    return principal


def require_role(
    *roles: PrincipalRole,
) -> Callable[..., Coroutine[Any, Any, Principal | None]]:
    """A dependency *factory* -- `Depends(require_role(PrincipalRole.ADMIN))`
    -- returning a dependency that calls `get_current_principal` and
    raises `AuthorizationError` if the resolved principal's role isn't one
    of `roles`. When `Settings.AUTH_ENABLED` is `False` (an explicit
    deployment-level override of the approved `True` default, see
    `docs/milestones/M13.md` §13.1), `get_current_principal` is not called
    at all -- every route using this dependency functions exactly as it
    did before M13, returning `None` rather than a real `Principal`. A
    handler that needs to distinguish "authenticated as X" from "running
    with authentication disabled" (e.g. `resolve_verdict_review`, see
    `docs/milestones/M13.md` §5.6) checks for `None`; every other handler
    only cares that this dependency didn't raise."""

    async def _require_role(
        request: Request,
        auth_enabled: bool = Depends(get_auth_enabled),
        db_engine: Engine = Depends(get_db_engine),
        principal_repository: PrincipalRepository = Depends(get_principal_repository),
    ) -> Principal | None:
        if not auth_enabled:
            return None
        principal = await get_current_principal(request, db_engine, principal_repository)
        if principal.role not in roles:
            raise AuthorizationError(
                f"principal role {principal.role.value!r} is not permitted for this action"
            )
        return principal

    return _require_role
