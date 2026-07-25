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
"""

from __future__ import annotations

from fastapi import Request

from gov_platform.adapters.base import Adapter
from gov_platform.adapters.synthetic import SyntheticSourcePayload
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.normalization.service import NormalizationService


def get_adapter(request: Request) -> Adapter[SyntheticSourcePayload]:
    adapter: Adapter[SyntheticSourcePayload] = request.app.state.adapter
    return adapter


def get_normalization_service(request: Request) -> NormalizationService:
    service: NormalizationService = request.app.state.normalization_service
    return service


def get_governance_engine(request: Request) -> GovernanceEngine:
    engine: GovernanceEngine = request.app.state.governance_engine
    return engine


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store
