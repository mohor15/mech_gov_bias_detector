"""Repository for M9's `VerdictReview` — architecture §12.

`create` is an idempotent upsert (`INSERT ... ON CONFLICT ... DO NOTHING`,
matching the partial unique index `one_open_verdict_review_per_verdict`
from migration `0023`), not a plain insert — both the live write path
(`audit/evidence_store.py`) and the reconciliation tool
(`human_review/backfill_reviews.py`) can race each other or themselves for
the same `verdict_id`, and a plain `INSERT` would let whichever writer
loses that race fail outright rather than silently no-op. Returns `None`
on conflict (an active review already exists), never raises for that case
— see `docs/milestones/M9.md` §3.4/§4.8.

`claim`/`release`/`resolve` are each a single conditional `UPDATE ...
WHERE id = :id AND status = '<expected>'` (and, for `resolve`, `AND
reviewer = :reviewer`), not a `session.get()`-then-mutate two-step —
`PopulationPolicyBindingRepository.set_lifecycle_state`'s read-then-write
shape has no such protection (a genuine, pre-existing race found as a
byproduct of designing *this* module, see `docs/milestones/M9.md` §9.6),
and a review claim/resolve race is materially more consequential than a
binding-lifecycle race: it decides who is accountable for a real bias
finding, not just whether a binding is active. A conflicting call (wrong
status, or a `reviewer` that doesn't match who claimed it) raises
`ValueError` — the Admin API translates that into a `409`, never a `422`
(this codebase's global `ValueError` handler defaults to `422`; the API
layer here catches this specific `ValueError` itself before it would ever
reach that handler, see `api/admin/verdict_reviews.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from gov_platform.db.models import VerdictReviewRow, VerdictRow
from gov_platform.schemas.human_review import (
    VerdictReview,
    VerdictReviewResolution,
    VerdictReviewStatus,
)
from gov_platform.schemas.verdict import VerdictStatus


class VerdictReviewRepository:
    def create(self, session: Session, verdict_id: str) -> VerdictReview | None:
        """Creates an `OPEN` review for `verdict_id`, unless an *active*
        (non-`RESOLVED`) one already exists, in which case this is a
        silent no-op (`None`) — never a conflict error. A verdict whose
        prior review already reached `RESOLVED` can be reopened this way;
        the partial unique index permits a second, independent row."""
        row_id = str(uuid4())
        created_at = datetime.now(UTC)
        statement = (
            pg_insert(VerdictReviewRow)
            .values(
                id=row_id,
                verdict_id=verdict_id,
                status=VerdictReviewStatus.OPEN.value,
                created_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[VerdictReviewRow.verdict_id],
                index_where=VerdictReviewRow.status != VerdictReviewStatus.RESOLVED.value,
            )
            .returning(VerdictReviewRow.id)
        )
        inserted_id = session.execute(statement).scalar_one_or_none()
        session.flush()
        if inserted_id is None:
            return None
        return VerdictReview(
            id=row_id,
            verdict_id=verdict_id,
            status=VerdictReviewStatus.OPEN,
            created_at=created_at,
        )

    def get(self, session: Session, review_id: str) -> VerdictReview | None:
        row = session.get(VerdictReviewRow, review_id)
        return self._to_model(row) if row is not None else None

    def list_all(
        self,
        session: Session,
        *,
        status: VerdictReviewStatus | None = None,
        severity: VerdictStatus | None = None,
    ) -> list[VerdictReview]:
        """Defaults to oldest-open-first (`created_at` ascending) — with
        no pagination and no notification mechanism, a newest-first
        default would bury the stalest, most-overdue items at the bottom
        of the response (`docs/milestones/M9.md` §3.7/§7). `severity`
        filters by the *referenced Verdict's* `status` (there is no
        denormalized severity column on this table — `VerdictStatus`
        already encodes it), added so `RECOMMEND_HOLD` items aren't
        buried among the more numerous `ESCALATE_FOR_REVIEW` ones in one
        undifferentiated queue."""
        statement = select(VerdictReviewRow).order_by(VerdictReviewRow.created_at)
        if status is not None:
            statement = statement.where(VerdictReviewRow.status == status.value)
        if severity is not None:
            statement = statement.join(
                VerdictRow, VerdictRow.id == VerdictReviewRow.verdict_id
            ).where(VerdictRow.status == severity.value)
        rows = session.execute(statement).scalars()
        return [self._to_model(row) for row in rows]

    def claim(self, session: Session, review_id: str, reviewer: str) -> VerdictReview:
        now = datetime.now(UTC)
        statement = (
            update(VerdictReviewRow)
            .where(
                VerdictReviewRow.id == review_id,
                VerdictReviewRow.status == VerdictReviewStatus.OPEN.value,
            )
            .values(
                status=VerdictReviewStatus.IN_REVIEW.value,
                reviewer=reviewer,
                claimed_at=now,
            )
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"verdict review {review_id!r} is not OPEN (already claimed, resolved, "
                "or does not exist)"
            )
        session.flush()
        row = session.get(VerdictReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    def release(self, session: Session, review_id: str) -> VerdictReview:
        statement = (
            update(VerdictReviewRow)
            .where(
                VerdictReviewRow.id == review_id,
                VerdictReviewRow.status == VerdictReviewStatus.IN_REVIEW.value,
            )
            .values(status=VerdictReviewStatus.OPEN.value, reviewer=None, claimed_at=None)
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"verdict review {review_id!r} is not IN_REVIEW (not currently claimed, "
                "already resolved, or does not exist)"
            )
        session.flush()
        row = session.get(VerdictReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    def resolve(
        self,
        session: Session,
        review_id: str,
        *,
        reviewer: str,
        resolution: VerdictReviewResolution,
        notes: str,
    ) -> VerdictReview:
        """`reviewer` must match the value recorded at `claim` time — a
        cheap, pre-authentication integrity check (this platform has no
        real reviewer identity to enforce): it cannot stop a malicious
        actor, but it does catch accidental cross-wiring (two browser
        tabs, a copy-pasted request against the wrong item) for free. A
        status mismatch and a reviewer mismatch are both zero-rows-affected
        -> `ValueError`; the caller does not need to distinguish which one
        occurred (`docs/milestones/M9.md` §3.3/§7)."""
        now = datetime.now(UTC)
        statement = (
            update(VerdictReviewRow)
            .where(
                VerdictReviewRow.id == review_id,
                VerdictReviewRow.status == VerdictReviewStatus.IN_REVIEW.value,
                VerdictReviewRow.reviewer == reviewer,
            )
            .values(
                status=VerdictReviewStatus.RESOLVED.value,
                resolution=resolution.value,
                resolution_notes=notes,
                resolved_at=now,
            )
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"verdict review {review_id!r} cannot be resolved by reviewer {reviewer!r} "
                "(not IN_REVIEW, already resolved, does not exist, or claimed by someone else)"
            )
        session.flush()
        row = session.get(VerdictReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    @staticmethod
    def _to_model(row: VerdictReviewRow) -> VerdictReview:
        return VerdictReview(
            id=row.id,
            verdict_id=row.verdict_id,
            status=VerdictReviewStatus(row.status),
            reviewer=row.reviewer,
            resolution=VerdictReviewResolution(row.resolution) if row.resolution else None,
            resolution_notes=row.resolution_notes,
            created_at=row.created_at,
            claimed_at=row.claimed_at,
            resolved_at=row.resolved_at,
        )
