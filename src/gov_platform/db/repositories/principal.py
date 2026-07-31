"""Repository for M13's `Principal` — architecture (no numbered section;
see `docs/milestones/M13.md` Sourcing note).

`create` is the **only** place the plaintext bearer token is ever
available — returned once, to the CLI caller (`access/create_principal.py`),
and never persisted or logged anywhere (mirrors how a real API-key
issuance flow -- GitHub, Stripe, AWS -- shows the secret exactly once at
creation time). Every other method deals only in `token_hash`.

`revoke` is a single conditional `UPDATE ... WHERE id = :id AND
revoked_at IS NULL` — not a `session.get()`-then-mutate two-step, the
same materially stronger concurrency-safety pattern
`VerdictReviewRepository.claim`/`release`/`resolve` (M9) already
established over `PopulationPolicyBindingRepository.set_lifecycle_state`'s
own read-then-write shape (a genuine, documented pre-existing race —
`docs/milestones/M9.md` §9.6). A `DELETE` is deliberately never issued —
"never destroy, only supersede", the same discipline already applied to
a resolved `VerdictReview`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from gov_platform.access.tokens import generate_token, hash_token
from gov_platform.db.models import PrincipalRow
from gov_platform.schemas.principal import Principal, PrincipalRole


class PrincipalRepository:
    def create(self, session: Session, *, name: str, role: PrincipalRole) -> tuple[Principal, str]:
        """Generates a fresh token, persists only its hash, and returns
        both the new `Principal` and the plaintext token -- the one and
        only time the plaintext is ever available."""
        token = generate_token()
        row = PrincipalRow(
            id=str(uuid4()),
            name=name,
            role=role.value,
            token_hash=hash_token(token),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return self._to_model(row), token

    def get_by_token_hash(self, session: Session, token_hash: str) -> Principal | None:
        """The hot path, called on every authenticated request -- backed
        by `token_hash`'s own `UNIQUE` constraint (migration `0028`) for
        O(1) lookup. Returns a revoked principal too (not filtered out
        here) -- `get_current_principal` is the one place that decides
        what a revoked credential means for a request."""
        row = session.execute(
            select(PrincipalRow).where(PrincipalRow.token_hash == token_hash)
        ).scalar_one_or_none()
        return self._to_model(row) if row is not None else None

    def revoke(self, session: Session, principal_id: str) -> Principal:
        now = datetime.now(UTC)
        statement = (
            update(PrincipalRow)
            .where(PrincipalRow.id == principal_id, PrincipalRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        result = session.execute(statement)
        assert isinstance(result, CursorResult)  # a Core UPDATE always returns one
        if result.rowcount == 0:
            raise ValueError(
                f"principal {principal_id!r} cannot be revoked (already revoked, or does not exist)"
            )
        session.flush()
        row = session.get(PrincipalRow, principal_id, populate_existing=True)
        assert row is not None  # just updated above, in this same transaction
        return self._to_model(row)

    def list(self, session: Session) -> list[Principal]:
        rows = session.execute(select(PrincipalRow).order_by(PrincipalRow.created_at)).scalars()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: PrincipalRow) -> Principal:
        return Principal(
            id=row.id,
            name=row.name,
            role=PrincipalRole(row.role),
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )
