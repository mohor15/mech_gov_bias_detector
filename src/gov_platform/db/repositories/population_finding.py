"""Repository for M6's Population Findings — architecture §13.

`PopulationFindingRecord` is the read-facing view — `PopulationFinding`
(`schemas/population_finding.py`) plus `signature`/`signing_key_id` —
mirroring the split `audit/evidence_store.py` draws between
`GovernanceVerdict` (no signature) and `EvidenceRecord` (has one): a
finding's domain identity doesn't include how it was signed, but a reader
needs both.

`create` translates the `UNIQUE (population_policy_id, system_id,
window_start, window_end)` constraint (migration `0015`) into a clean
`ValueError` — per `docs/milestones/M6.md` §13.13, this is what makes a
duplicate/overlapping run of `population_engine/run_policies.py` a
detectable no-op rather than a race producing two disagreeing findings
for "the same" window.

M8 (architecture §10): `parameters_used` round-trips `NULL` as Python
`None`, never as `{}` — a real, easy-to-get-wrong mapping detail this
milestone depends on. `None` means "this finding predates parameter
tracking" (every record created before M8); collapsing it to `{}` here
would defeat `audit/verify_population_findings.py`'s `exclude_none=True`
hash-compatibility fix for every such record. See
`docs/milestones/M8.md` §4.5/§13.18.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gov_platform.db.models import PopulationFindingRow
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome


class PopulationFindingRecord(BaseModel):
    """Read-facing view of a persisted population finding."""

    model_config = ConfigDict(frozen=True)

    id: str
    population_policy_id: str
    population_policy_version: str
    system_id: str
    window_start: datetime
    window_end: datetime
    outcome: PopulationFindingOutcome
    metric_values: dict[str, float]
    classification_snapshot: dict[str, str]
    parameters_used: dict[str, float] | None = None
    rationale: str
    evaluated_at: datetime
    signature: str | None = None
    signing_key_id: str | None = None

    def as_population_finding(self) -> PopulationFinding:
        """Drops the signature fields -- what `audit/verify_population_findings.py`
        re-hashes and verifies against `signature`, since a signature can
        never legitimately cover itself."""
        return PopulationFinding(
            population_finding_id=self.id,
            population_policy_id=self.population_policy_id,
            population_policy_version=self.population_policy_version,
            system_id=self.system_id,
            window_start=self.window_start,
            window_end=self.window_end,
            outcome=self.outcome,
            metric_values=self.metric_values,
            classification_snapshot=self.classification_snapshot,
            parameters_used=self.parameters_used,
            rationale=self.rationale,
            evaluated_at=self.evaluated_at,
        )


class PopulationFindingRepository:
    def create(
        self,
        session: Session,
        finding: PopulationFinding,
        *,
        signature: str | None,
        signing_key_id: str | None,
    ) -> PopulationFindingRecord:
        row = PopulationFindingRow(
            id=finding.population_finding_id,
            population_policy_id=finding.population_policy_id,
            population_policy_version=finding.population_policy_version,
            system_id=finding.system_id,
            window_start=finding.window_start,
            window_end=finding.window_end,
            outcome=finding.outcome.value,
            metric_values=json.dumps(finding.metric_values),
            classification_snapshot=json.dumps(finding.classification_snapshot),
            parameters_used=(
                json.dumps(finding.parameters_used) if finding.parameters_used is not None else None
            ),
            rationale=finding.rationale,
            evaluated_at=finding.evaluated_at,
            signature=signature,
            signing_key_id=signing_key_id,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                f"a population finding for population policy {finding.population_policy_id!r} "
                f"system {finding.system_id!r} window [{finding.window_start}, "
                f"{finding.window_end}) already exists"
            ) from exc
        return self._to_model(row)

    def get(self, session: Session, finding_id: str) -> PopulationFindingRecord | None:
        row = session.get(PopulationFindingRow, finding_id)
        return self._to_model(row) if row is not None else None

    def list_all(self, session: Session) -> list[PopulationFindingRecord]:
        rows = session.execute(
            select(PopulationFindingRow).order_by(PopulationFindingRow.evaluated_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    def list_for_system(self, session: Session, system_id: str) -> list[PopulationFindingRecord]:
        rows = session.execute(
            select(PopulationFindingRow)
            .where(PopulationFindingRow.system_id == system_id)
            .order_by(PopulationFindingRow.evaluated_at)
        ).scalars()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: PopulationFindingRow) -> PopulationFindingRecord:
        return PopulationFindingRecord(
            id=row.id,
            population_policy_id=row.population_policy_id,
            population_policy_version=row.population_policy_version,
            system_id=row.system_id,
            window_start=row.window_start,
            window_end=row.window_end,
            outcome=PopulationFindingOutcome(row.outcome),
            metric_values=json.loads(row.metric_values),
            classification_snapshot=json.loads(row.classification_snapshot),
            parameters_used=json.loads(row.parameters_used)
            if row.parameters_used is not None
            else None,
            rationale=row.rationale,
            evaluated_at=row.evaluated_at,
            signature=row.signature,
            signing_key_id=row.signing_key_id,
        )
