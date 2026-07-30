from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from gov_platform.audit.encryption import (
    UNREADABLE_PLACEHOLDER,
    FieldDecryptionError,
    FieldEncryptor,
    NoOpFieldEncryptor,
    decrypt_field,
)
from gov_platform.db.models import ProtectedAttributeResolutionRow
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)

logger = logging.getLogger(__name__)


class ProtectedAttributeResolutionRepository:
    """Persists `ProtectedAttributeResolver`'s output.

    `ResolvedProtectedAttribute` is a value object with no identity of its
    own (unlike `Finding`/`Verdict`, which carry their own id from the
    domain layer) — this repository generates the row's primary key at
    persistence time, the same role `ModelVersionRepository.create` plays
    for `ModelVersion`.

    `encryptor` application-level-encrypts `proxy_basis` (M11, architecture
    §13) — read via `decision_event_id` joins only, never filtered,
    grouped, or ordered by its own value, unlike its sibling
    `attribute_name` (see docs/milestones/M11.md §4.1/§5.1 for why
    `attribute_name` cannot be encrypted: `list_by_decision_event`'s own
    `ORDER BY` would silently return meaningless order for ciphertext).
    Defaults to `NoOpFieldEncryptor` — encryption off.
    """

    def __init__(self, *, encryptor: FieldEncryptor | None = None) -> None:
        self._encryptor = encryptor or NoOpFieldEncryptor()

    def create(self, session: Session, resolution: ResolvedProtectedAttribute) -> None:
        encrypted_proxy_basis = (
            self._encryptor.encrypt(resolution.proxy_basis)
            if resolution.proxy_basis is not None
            else None
        )
        row = ProtectedAttributeResolutionRow(
            id=str(uuid4()),
            decision_event_id=resolution.decision_event_id,
            attribute_name=resolution.attribute_name,
            classification=resolution.classification.value,
            proxy_basis=encrypted_proxy_basis,
            resolved_at=resolution.resolved_at,
        )
        session.add(row)
        session.flush()

    def list_by_decision_event(
        self, session: Session, decision_event_id: str
    ) -> list[ResolvedProtectedAttribute]:
        statement = (
            select(ProtectedAttributeResolutionRow)
            .where(ProtectedAttributeResolutionRow.decision_event_id == decision_event_id)
            .order_by(ProtectedAttributeResolutionRow.attribute_name)
        )
        rows = session.execute(statement).scalars()
        return [self._to_model(row) for row in rows]

    def _to_model(self, row: ProtectedAttributeResolutionRow) -> ResolvedProtectedAttribute:
        return ResolvedProtectedAttribute(
            decision_event_id=row.decision_event_id,
            attribute_name=row.attribute_name,
            classification=ProtectedAttributeClassification(row.classification),
            proxy_basis=self._decrypt_proxy_basis(row.id, row.proxy_basis),
            resolved_at=row.resolved_at,
        )

    def _decrypt_proxy_basis(self, resolution_id: str, value: str | None) -> str | None:
        """Per-record containment, the identical policy
        `VerdictReviewRepository._decrypt_resolution_notes` applies to its
        own free-text field (docs/milestones/M11.md §5.1/§12.15):
        `proxy_basis` is not evidentiary content in the sense
        `evidence_chain.payload` is — it is `protected_attributes/classification.py`'s/
        `protected_attribute_rules`' own admin-configured `proxy_of` value,
        derived data (see `docs/milestones/M11.md` §4.4 on the limits of
        that claim), not a value this platform's tamper-evidence guarantee
        depends on. A decrypt failure degrades to `UNREADABLE_PLACEHOLDER`
        for this one row rather than crashing the whole caller."""
        if value is None:
            return None
        try:
            return decrypt_field(value, self._encryptor)
        except FieldDecryptionError:
            logger.warning(
                "protected_attribute_resolution_proxy_basis_undecryptable",
                extra={"extra_fields": {"resolution_id": resolution_id}},
            )
            return UNREADABLE_PLACEHOLDER
