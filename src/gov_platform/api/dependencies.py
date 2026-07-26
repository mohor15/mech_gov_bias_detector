"""FastAPI dependency providers.

Route handlers depend on these functions, never on concrete singletons
imported at module scope — this is what makes `api.app.create_app` a real
composition root and lets tests override any collaborator (e.g. pointing
the Evidence Store at a temp file) without monkeypatching module globals,
the trap V1 fell into with its bare module-level `pipeline = MechGovPipeline()`.

`get_adapter` returns the `Adapter` port, not the concrete `SyntheticAdapter`
— tightened during the M0 finalization review so route code depends on the
abstraction, not the implementation (DIP). `NormalizationService`,
`GovernanceEngine`, and `EvidenceStore` stay typed as concrete classes
deliberately: the architecture never defines them as swappable plugin
surfaces (only `Adapter` and `Policy` are ports), so introducing an
abstraction for them here would be speculative, not a fix.

M2 adds `get_credit_scorecard_adapter` and
`get_credit_scorecard_governance_engine` — a second adapter and a second,
independently-policied `GovernanceEngine`, one per ingestion route (see
`docs/milestones/M2.md` §11.1). No `get_protected_attribute_resolver`
provider exists: `ProtectedAttributeResolver` is an internal collaborator
of `EvidenceStore` and the new `Policy`, wired once in the composition
root — no route handler touches it directly, so it needs no FastAPI
dependency of its own, the same way `FindingRepository` doesn't either.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.engine import Engine

from gov_platform.adapters.base import Adapter
from gov_platform.adapters.credit_scorecard import CreditScorecardPayload
from gov_platform.adapters.synthetic import SyntheticSourcePayload
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.normalization.service import NormalizationService


def get_adapter(request: Request) -> Adapter[SyntheticSourcePayload]:
    adapter: Adapter[SyntheticSourcePayload] = request.app.state.adapter
    return adapter


def get_credit_scorecard_adapter(request: Request) -> Adapter[CreditScorecardPayload]:
    adapter: Adapter[CreditScorecardPayload] = request.app.state.credit_scorecard_adapter
    return adapter


def get_credit_scorecard_governance_engine(request: Request) -> GovernanceEngine:
    engine: GovernanceEngine = request.app.state.credit_scorecard_governance_engine
    return engine


def get_normalization_service(request: Request) -> NormalizationService:
    service: NormalizationService = request.app.state.normalization_service
    return service


def get_governance_engine(request: Request) -> GovernanceEngine:
    engine: GovernanceEngine = request.app.state.governance_engine
    return engine


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


def get_db_engine(request: Request) -> Engine:
    """M1: the one shared Engine, used directly by the Admin API's routes
    (which need their own short-lived Session, distinct from EvidenceStore's
    internal one) — see api.app for why this is a single shared engine."""
    engine: Engine = request.app.state.db_engine
    return engine


def get_system_repository(request: Request) -> SystemRepository:
    repository: SystemRepository = request.app.state.system_repository
    return repository
