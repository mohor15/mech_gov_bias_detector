"""The Ingestion API — architecture §15, M3.

M0/M1/M2 hand-wrote one route per adapter, each hardcoded in this module
and wired directly in `api/app.py`'s composition root. M3 replaces that
with routes *generated* from the plugin registry (`plugins/registry.py`):
one real, independently-typed FastAPI route per adapter this process
knows about, built at app-construction time by inspecting
`Adapter.translate`'s own type annotation for its payload type — not
hand-written per adapter, and not requiring a database at construction
time (see `api/app.py`'s module docstring on why `create_app()` must stay
DB-free).

Building a route with a *dynamic* payload type (it varies per adapter)
while keeping FastAPI's real request validation and OpenAPI generation —
the whole reason this approach was chosen over a single generic endpoint,
see `docs/milestones/M3.md` §13.4 — needs one deliberate trick. Every
module in this codebase uses `from __future__ import annotations`
(PEP 563), which turns ordinary type annotations into strings resolved
later against a function's *module* globals. A dynamically generated
route's payload type is a local variable inside this factory, not a name
in any module's global namespace, so a string annotation for it could
never resolve. The fix: set the generated handler's `payload` entry in
`__annotations__` directly to the already-resolved class object, *after*
the function is defined, instead of writing a literal annotation in
source. FastAPI resolves annotations via `typing.get_type_hints`, which
leaves an already-non-string value alone — so this sidesteps string
resolution entirely rather than fighting it.

Per-request dispatch, not construction-time: route *existence* is a pure
function of which adapters this process's code has registered in-process
(`plugins/bootstrap.py`) — no database read. Which `Policy` actually
governs a given request (`PRODUCTION` vs `SHADOW`) is resolved fresh on
every request from `plugin_registrations`, so promoting/demoting a policy
via the Admin API takes effect on the very next request, no app restart
needed. An adapter with no `PRODUCTION`/`SHADOW` registration (still
`DRAFT`, or never registered at all) rejects real traffic with a 503 —
`SHADOW` and `PRODUCTION` currently behave identically for an *adapter*
(both fully process and persist); M3 does not yet give adapter-level
`SHADOW` a distinct meaning from `PRODUCTION` the way it does for
policies (see `docs/milestones/M3.md`'s production-readiness review).

Handlers are plain `def`, not `async def` — same reasoning as M0's
original ingestion route: every operation here is synchronous.

M4: an adapter can be governed by more than one policy family (architecture
§8, policy plurality — see `docs/milestones/M4.md`). The per-request
resolution loop below runs once per governing family, collecting one
`PRODUCTION` policy from each into a single `GovernanceEngine`, which
aggregates their Findings into one Verdict. Any family missing a live
`PRODUCTION` policy fails the whole request — no verdict is ever built from
a partial policy set. `SHADOW` execution is unaffected: it was already
scoped per policy family, not per adapter.

M5: which families govern an adapter is resolved from `policy_bindings`
(`PolicyBindingRepository.list_active_for_adapter`), not a
`governing_policy_ids` class attribute — a database fact, changeable via
the Admin API without a redeploy, the same "no app restart needed"
property M3 already established for lifecycle promotion. Each active
binding also carries a `PolicySeverity`, bundled with its resolved
`Policy` into a `GoverningPolicy` so `GovernanceEngine` can compute the
real four-state `VerdictStatus` (see `governance_engine/engine.py`) instead
of M4's binary placeholder. An adapter with zero active bindings fails the
whole request with a 503, the same "no partial governance" discipline
applied to a single missing family.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from typing import Any, cast, get_type_hints

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.adapters.base import Adapter
from gov_platform.api.dependencies import (
    get_db_engine,
    get_evidence_store,
    get_normalization_service,
    get_plugin_registration_repository,
    get_policy_binding_repository,
    get_shadow_finding_repository,
)
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.governance_engine.engine import GovernanceEngine, GoverningPolicy
from gov_platform.normalization.service import NormalizationService
from gov_platform.plugins import registry
from gov_platform.plugins.sandbox import run_sandboxed
from gov_platform.schemas.plugin_registration import (
    PluginLifecycleState,
    PluginRegistration,
    PluginType,
)
from gov_platform.schemas.verdict import VerdictStatus

logger = logging.getLogger(__name__)


class IngestionResponse(BaseModel):
    decision_event_id: str
    verdict_id: str
    status: VerdictStatus
    evidence_sequence_number: int
    evidence_record_hash: str


def _payload_type_for(adapter_cls: type[Adapter[Any]]) -> type[BaseModel]:
    """The concrete Pydantic type `adapter_cls.translate` accepts,
    resolved from its own (PEP 563, postponed) type annotation against
    its defining module's globals — not guessed from the generic
    `Adapter[TPayload]` parameterization, which isn't reliably
    introspectable at runtime without extra bookkeeping this avoids."""
    hints = get_type_hints(adapter_cls.translate)
    return cast(type[BaseModel], hints["raw_payload"])


def _build_handler(
    adapter: Adapter[Any], payload_type: type[BaseModel]
) -> Callable[..., IngestionResponse]:
    def handler(
        payload: Any,
        normalization_service: NormalizationService = Depends(get_normalization_service),
        evidence_store: EvidenceStore = Depends(get_evidence_store),
        db_engine: Engine = Depends(get_db_engine),
        plugin_registration_repository: PluginRegistrationRepository = Depends(
            get_plugin_registration_repository
        ),
        policy_binding_repository: PolicyBindingRepository = Depends(get_policy_binding_repository),
        shadow_finding_repository: ShadowFindingRepository = Depends(get_shadow_finding_repository),
    ) -> IngestionResponse:
        with Session(db_engine) as session:
            adapter_registration = plugin_registration_repository.get_by_identity(
                session,
                plugin_type=PluginType.ADAPTER,
                plugin_id=adapter.adapter_id,
                version=adapter.version,
            )
        if adapter_registration is None or adapter_registration.lifecycle_state is (
            PluginLifecycleState.DRAFT
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"adapter '{adapter.adapter_id}' is not yet accepting production traffic",
            )

        decision_event = run_sandboxed(lambda: adapter.translate(payload))
        normalized_event = normalization_service.normalize(decision_event)

        # M5: one production policy per active PolicyBinding, collected in
        # binding-creation order so GovernanceEngine's findings come out
        # deterministic (see docs/milestones/M4.md §4/§13.7) -- and any
        # family missing a PRODUCTION policy fails the whole request
        # immediately, the same "no partial verdicts" discipline M3
        # already applied to a single family.
        production_policies: list[GoverningPolicy] = []
        shadow_registrations: list[PluginRegistration] = []
        with Session(db_engine) as session:
            bindings = policy_binding_repository.list_active_for_adapter(
                session, adapter.adapter_id
            )
            if not bindings:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"adapter '{adapter.adapter_id}' has no active policy bindings",
                )
            for binding in bindings:
                policy_registrations = plugin_registration_repository.list_by_type_and_plugin_id(
                    session, plugin_type=PluginType.POLICY, plugin_id=binding.policy_id
                )
                production_registration = next(
                    (
                        r
                        for r in policy_registrations
                        if r.lifecycle_state is PluginLifecycleState.PRODUCTION
                    ),
                    None,
                )
                if production_registration is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"no PRODUCTION policy registered for '{binding.policy_id}'",
                    )
                production_policy_cls = registry.get_policy_class(
                    production_registration.plugin_id, production_registration.version
                )
                if production_policy_cls is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=(
                            f"PRODUCTION policy '{production_registration.plugin_id}' "
                            f"version {production_registration.version} is registered but no "
                            "longer deployed in this process"
                        ),
                    )
                production_policies.append(
                    GoverningPolicy(policy=production_policy_cls(), severity=binding.severity)
                )
                shadow_registrations.extend(
                    r
                    for r in policy_registrations
                    if r.lifecycle_state is PluginLifecycleState.SHADOW
                )

        engine = GovernanceEngine(governing_policies=production_policies)
        verdict = run_sandboxed(lambda: engine.govern(normalized_event))
        evidence_record = evidence_store.append(normalized_event, verdict)

        for shadow_registration in shadow_registrations:
            shadow_policy_cls = registry.get_policy_class(
                shadow_registration.plugin_id, shadow_registration.version
            )
            if shadow_policy_cls is None:
                continue  # registered in the DB but no longer deployed here -- skip it
            shadow_policy = shadow_policy_cls()
            try:
                # functools.partial binds shadow_policy.evaluate and
                # normalized_event immediately, not a closure over the
                # loop variable `shadow_policy` -- a lambda here would
                # resolve `shadow_policy` at call time, by which point the
                # loop may have already reassigned it to the next iteration's
                # policy (B023).
                shadow_finding = run_sandboxed(partial(shadow_policy.evaluate, normalized_event))
            except Exception:
                # A shadow policy exists to be evaluated safely, without
                # risk to real ingestion -- see docs/milestones/M3.md
                # §13.3. Its own failure must never surface to the caller.
                logger.exception(
                    "shadow_policy_evaluation_failed",
                    extra={"extra_fields": {"plugin_registration_id": shadow_registration.id}},
                )
                continue
            with Session(db_engine) as session:
                shadow_finding_repository.create(
                    session, shadow_finding, plugin_registration_id=shadow_registration.id
                )
                session.commit()

        return IngestionResponse(
            decision_event_id=normalized_event.event_id,
            verdict_id=verdict.verdict_id,
            status=verdict.status,
            evidence_sequence_number=evidence_record.sequence_number,
            evidence_record_hash=evidence_record.record_hash,
        )

    # See this module's docstring: sidesteps PEP 563 string-annotation
    # resolution for the one parameter whose type genuinely varies per
    # generated route.
    handler.__annotations__["payload"] = payload_type
    handler.__annotations__["return"] = IngestionResponse
    handler.__name__ = f"ingest_{adapter.adapter_id.replace('-', '_')}_event"
    return handler


def build_ingestion_router() -> APIRouter:
    """One real route per adapter registered in-process (see
    `plugins.bootstrap`). Called once at app-construction time; reads no
    database — see this module's docstring."""
    router = APIRouter(tags=["ingestion"])

    for adapter_id, version in sorted(registry.known_adapter_keys()):
        adapter_cls = registry.get_adapter_class(adapter_id, version)
        assert adapter_cls is not None  # just came from known_adapter_keys()
        adapter = adapter_cls()
        payload_type = _payload_type_for(adapter_cls)
        handler = _build_handler(adapter, payload_type)

        router.add_api_route(
            f"/events/{adapter.adapter_id}",
            handler,
            methods=["POST"],
            response_model=IngestionResponse,
            status_code=status.HTTP_201_CREATED,
            name=handler.__name__,
        )

    return router
