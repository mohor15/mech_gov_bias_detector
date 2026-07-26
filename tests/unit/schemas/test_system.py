from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.system import System


def _system(**overrides: object) -> System:
    defaults: dict[str, object] = {
        "id": "sys-001",
        "name": "synthetic-scorecard",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return System(**defaults)  # type: ignore[arg-type]


def test_valid_system_constructs_with_optional_fields_defaulting_to_none() -> None:
    system = _system()
    assert system.domain is None
    assert system.risk_tier is None
    assert system.owner is None


def test_valid_system_constructs_with_optional_fields_provided() -> None:
    system = _system(domain="FINANCE", risk_tier="HIGH", owner="risk-team")
    assert system.domain == "FINANCE"
    assert system.risk_tier == "HIGH"
    assert system.owner == "risk-team"


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        _system(name="")


def test_system_is_frozen() -> None:
    system = _system()
    with pytest.raises(ValidationError):
        system.name = "mutated"  # type: ignore[misc]
