"""`ProtectedAttributeResolutionRepository` — real Postgres round trip.
CI-only (see conftest.requires_postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.decision_event import DecisionEventRepository
from gov_platform.db.repositories.model_version import ModelVersionRepository
from gov_platform.db.repositories.protected_attribute_resolution import (
    ProtectedAttributeResolutionRepository,
)
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.schemas.protected_attribute import (
    ProtectedAttributeClassification,
    ResolvedProtectedAttribute,
)
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def test_list_by_decision_event_returns_nothing_for_an_unresolved_event(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        repository = ProtectedAttributeResolutionRepository()
        assert repository.list_by_decision_event(session, "no-such-event") == []


def test_create_and_list_round_trips_direct_proxied_and_withheld(
    db_engine: Engine, make_decision_event: Any
) -> None:
    with Session(db_engine) as session:
        system = SystemRepository().create(session, name=f"sys-{uuid4()}", domain="FINANCE")
        model_version = ModelVersionRepository().create(
            session, system_id=system.id, version="1.0.0"
        )
        event = make_decision_event(event_id=f"evt-{uuid4()}", system_id=system.name)
        DecisionEventRepository().create(session, event, model_version_id=model_version.id)

        resolved_at = datetime(2026, 1, 1, tzinfo=UTC)
        repository = ProtectedAttributeResolutionRepository()
        repository.create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="race",
                classification=ProtectedAttributeClassification.DIRECT,
                resolved_at=resolved_at,
            ),
        )
        repository.create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="zip_code",
                classification=ProtectedAttributeClassification.PROXIED,
                proxy_basis="race",
                resolved_at=resolved_at,
            ),
        )
        repository.create(
            session,
            ResolvedProtectedAttribute(
                decision_event_id=event.event_id,
                attribute_name="gender",
                classification=ProtectedAttributeClassification.WITHHELD,
                resolved_at=resolved_at,
            ),
        )
        session.commit()

        resolutions = repository.list_by_decision_event(session, event.event_id)

    by_attribute = {r.attribute_name: r for r in resolutions}
    assert by_attribute["race"].classification is ProtectedAttributeClassification.DIRECT
    assert by_attribute["race"].proxy_basis is None
    assert by_attribute["zip_code"].classification is ProtectedAttributeClassification.PROXIED
    assert by_attribute["zip_code"].proxy_basis == "race"
    assert by_attribute["gender"].classification is ProtectedAttributeClassification.WITHHELD
