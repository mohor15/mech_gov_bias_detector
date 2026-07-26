from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.model_version import UNSPECIFIED_VERSION, ModelVersion


def _model_version(**overrides: object) -> ModelVersion:
    defaults: dict[str, object] = {
        "id": "mv-001",
        "system_id": "sys-001",
        "version": UNSPECIFIED_VERSION,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ModelVersion(**defaults)  # type: ignore[arg-type]


def test_valid_model_version_constructs() -> None:
    model_version = _model_version()
    assert model_version.version == UNSPECIFIED_VERSION


def test_empty_version_rejected() -> None:
    with pytest.raises(ValidationError):
        _model_version(version="")


def test_model_version_is_frozen() -> None:
    model_version = _model_version()
    with pytest.raises(ValidationError):
        model_version.version = "mutated"  # type: ignore[misc]
