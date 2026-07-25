"""The Ingestion API — the one endpoint this milestone exists to prove.

Hardwired to `SyntheticAdapter` for M0: there is exactly one adapter, so
there is nothing to route between yet. Adapter registry/discovery so this
endpoint can dispatch to whichever adapter a given `system_id` requires is
M3 scope (architecture §6) — introducing it now, for one adapter, would be
speculative generality with no second case to validate it against. (The
handler below depends on the `Adapter` port, not `SyntheticAdapter`
concretely, per the DIP fix in `api.dependencies` — but the request body's
*schema* is still tied to one adapter's wire format, which is the part that
is genuinely M3's job to generalize, not this one.)

Malformed request bodies never reach this handler: FastAPI validates
`SyntheticSourcePayload` before the function body runs and returns a 422
with the validation error, never a 500 — this is what M0's acceptance
criterion "malformed input is rejected with a schema validation error, not
a 500" actually depends on, and it is enforced by the type annotation below,
not by a try/except this handler would otherwise need.

Defined as a plain `def`, not `async def`: every operation inside it
(`Adapter.translate`, `NormalizationService.normalize`,
`GovernanceEngine.govern`, `EvidenceStore.append`) is synchronous — none of
it `await`s anything. An `async def` handler runs directly on the event
loop, so blocking calls inside one block every other concurrent request on
that worker; FastAPI runs a plain `def` handler in a threadpool instead,
which is the correct, minimal fix for a fully-synchronous handler. Found
during the M0 finalization review — see the production-readiness review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from gov_platform.adapters.base import Adapter
from gov_platform.adapters.synthetic import SyntheticSourcePayload
from gov_platform.api.dependencies import (
    get_adapter,
    get_evidence_store,
    get_governance_engine,
    get_normalization_service,
)
from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.governance_engine.engine import GovernanceEngine
from gov_platform.normalization.service import NormalizationService
from gov_platform.schemas.verdict import VerdictStatus

router = APIRouter(tags=["ingestion"])


class IngestionResponse(BaseModel):
    decision_event_id: str
    verdict_id: str
    status: VerdictStatus
    evidence_sequence_number: int
    evidence_record_hash: str


@router.post("/events", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
def ingest_event(
    payload: SyntheticSourcePayload,
    adapter: Adapter[SyntheticSourcePayload] = Depends(get_adapter),
    normalization_service: NormalizationService = Depends(get_normalization_service),
    governance_engine: GovernanceEngine = Depends(get_governance_engine),
    evidence_store: EvidenceStore = Depends(get_evidence_store),
) -> IngestionResponse:
    """The full M0 vertical slice: adapter -> normalize -> governance -> evidence."""
    decision_event = adapter.translate(payload)
    normalized_event = normalization_service.normalize(decision_event)
    verdict = governance_engine.govern(normalized_event)
    evidence_record = evidence_store.append(normalized_event, verdict)

    return IngestionResponse(
        decision_event_id=normalized_event.event_id,
        verdict_id=verdict.verdict_id,
        status=verdict.status,
        evidence_sequence_number=evidence_record.sequence_number,
        evidence_record_hash=evidence_record.record_hash,
    )
