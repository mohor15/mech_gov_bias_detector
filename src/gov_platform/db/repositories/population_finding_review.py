"""Repository for M9's `PopulationFindingReview` — architecture §12.

Mirrors `db/repositories/verdict_review.py`'s `VerdictReviewRepository`
exactly, for `PopulationFinding` instead of `Verdict` — see that module's
docstring for the full reasoning behind the idempotent-upsert `create` and
the conditional-`UPDATE` `claim`/`release`/`resolve` shape. No `severity`
parameter on `list_all`: `PopulationFindingOutcome` is already binary
(`CLEAR`/`FLAGGED`), with no severity tier to filter by.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from gov_platform.db.models import PopulationFindingReviewRow
from gov_platform.schemas.human_review import (
    PopulationFindingReview,
    PopulationFindingReviewResolution,
    PopulationFindingReviewStatus,
)


class PopulationFindingReviewRepository:
    def create(
        self, session: Session, population_finding_id: str
    ) -> PopulationFindingReview | None:
        """Idempotent upsert — see `VerdictReviewRepository.create`'s
        docstring for the full reasoning. Returns `None` (never raises) if
        an active review already exists for this finding."""
        row_id = str(uuid4())
        created_at = datetime.now(UTC)
        statement = (
            pg_insert(PopulationFindingReviewRow)
            .values(
                id=row_id,
                population_finding_id=population_finding_id,
                status=PopulationFindingReviewStatus.OPEN.value,
                created_at=created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[PopulationFindingReviewRow.population_finding_id],
                index_where=(
                    PopulationFindingReviewRow.status
                    != PopulationFindingReviewStatus.RESOLVED.value
                ),
            )
            .returning(PopulationFindingReviewRow.id)
        )
        inserted_id = session.execute(statement).scalar_one_or_none()
        session.flush()
        if inserted_id is None:
            return None
        return PopulationFindingReview(
            id=row_id,
            population_finding_id=population_finding_id,
            status=PopulationFindingReviewStatus.OPEN,
            created_at=created_at,
        )

    def get(self, session: Session, review_id: str) -> PopulationFindingReview | None:
        row = session.get(PopulationFindingReviewRow, review_id)
        return self._to_model(row) if row is not None else None

    def list_all(
        self, session: Session, *, status: PopulationFindingReviewStatus | None = None
    ) -> list[PopulationFindingReview]:
        """Defaults to oldest-open-first — see
        `VerdictReviewRepository.list_all`'s docstring for why."""
        statement = select(PopulationFindingReviewRow).order_by(
            PopulationFindingReviewRow.created_at
        )
        if status is not None:
            statement = statement.where(PopulationFindingReviewRow.status == status.value)
        rows = session.execute(statement).scalars()
        return [self._to_model(row) for row in rows]

    def claim(self, session: Session, review_id: str, reviewer: str) -> PopulationFindingReview:
        now = datetime.now(UTC)
        statement = (
            update(PopulationFindingReviewRow)
            .where(
                PopulationFindingReviewRow.id == review_id,
                PopulationFindingReviewRow.status == PopulationFindingReviewStatus.OPEN.value,
            )
            .values(
                status=PopulationFindingReviewStatus.IN_REVIEW.value,
                reviewer=reviewer,
                claimed_at=now,
            )
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"population finding review {review_id!r} is not OPEN (already claimed, "
                "resolved, or does not exist)"
            )
        session.flush()
        row = session.get(PopulationFindingReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    def release(self, session: Session, review_id: str) -> PopulationFindingReview:
        statement = (
            update(PopulationFindingReviewRow)
            .where(
                PopulationFindingReviewRow.id == review_id,
                PopulationFindingReviewRow.status == PopulationFindingReviewStatus.IN_REVIEW.value,
            )
            .values(status=PopulationFindingReviewStatus.OPEN.value, reviewer=None, claimed_at=None)
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"population finding review {review_id!r} is not IN_REVIEW (not currently "
                "claimed, already resolved, or does not exist)"
            )
        session.flush()
        row = session.get(PopulationFindingReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    def resolve(
        self,
        session: Session,
        review_id: str,
        *,
        reviewer: str,
        resolution: PopulationFindingReviewResolution,
        notes: str,
    ) -> PopulationFindingReview:
        now = datetime.now(UTC)
        statement = (
            update(PopulationFindingReviewRow)
            .where(
                PopulationFindingReviewRow.id == review_id,
                PopulationFindingReviewRow.status == PopulationFindingReviewStatus.IN_REVIEW.value,
                PopulationFindingReviewRow.reviewer == reviewer,
            )
            .values(
                status=PopulationFindingReviewStatus.RESOLVED.value,
                resolution=resolution.value,
                resolution_notes=notes,
                resolved_at=now,
            )
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"population finding review {review_id!r} cannot be resolved by reviewer "
                f"{reviewer!r} (not IN_REVIEW, already resolved, does not exist, or claimed "
                "by someone else)"
            )
        session.flush()
        row = session.get(PopulationFindingReviewRow, review_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    @staticmethod
    def _to_model(row: PopulationFindingReviewRow) -> PopulationFindingReview:
        return PopulationFindingReview(
            id=row.id,
            population_finding_id=row.population_finding_id,
            status=PopulationFindingReviewStatus(row.status),
            reviewer=row.reviewer,
            resolution=(
                PopulationFindingReviewResolution(row.resolution) if row.resolution else None
            ),
            resolution_notes=row.resolution_notes,
            created_at=row.created_at,
            claimed_at=row.claimed_at,
            resolved_at=row.resolved_at,
        )
