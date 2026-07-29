from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gov_platform.schemas.population_policy_binding import (
    PopulationPolicyBinding,
    PopulationPolicyBindingLifecycleState,
)


def _binding(**overrides: object) -> PopulationPolicyBinding:
    defaults: dict[str, object] = {
        "id": "binding-001",
        "system_id": "sys-001",
        "population_policy_id": "adverse-impact-ratio",
        "lifecycle_state": PopulationPolicyBindingLifecycleState.ACTIVE,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PopulationPolicyBinding(**defaults)  # type: ignore[arg-type]


def test_valid_binding_constructs() -> None:
    binding = _binding()
    assert binding.lifecycle_state is PopulationPolicyBindingLifecycleState.ACTIVE


def test_binding_is_frozen() -> None:
    binding = _binding()
    with pytest.raises(ValidationError):
        binding.lifecycle_state = PopulationPolicyBindingLifecycleState.INACTIVE  # type: ignore[misc]


def test_binding_carries_no_adapter_id() -> None:
    """system_id-keyed, not adapter_id-keyed -- see
    docs/milestones/M6.md §13.8."""
    assert "adapter_id" not in PopulationPolicyBinding.model_fields
    assert "system_id" in PopulationPolicyBinding.model_fields


def test_parameters_defaults_to_an_empty_dict() -> None:
    """M8 (docs/milestones/M8.md §4.3): empty means "use the policy's own
    built-in defaults" -- every binding created before M8 has this
    behavior unchanged."""
    binding = _binding()
    assert binding.parameters == {}


def test_parameters_round_trips_a_real_dict() -> None:
    binding = _binding(parameters={"threshold": 0.75})
    assert binding.parameters == {"threshold": 0.75}
