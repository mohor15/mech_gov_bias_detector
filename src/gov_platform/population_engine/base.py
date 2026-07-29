"""The `PopulationPolicy` port — architecture §7, M6.

A third plugin surface alongside `Adapter` (§4.1) and `Policy` (§7) — the
first new port since M0. Justified because `Policy.evaluate`'s
single-event, `Finding`-per-`decision_event_id` contract is structurally
incompatible with an aggregate result: this is not two similar things
that happen to differ slightly, it is two genuinely different questions
("does this one decision violate a rule" vs. "does this population of
decisions show a statistical pattern") that only coincidentally share the
word "policy". See `docs/milestones/M6.md` §9/§13.3 for the full
reasoning.

`PopulationWindow` deliberately carries pre-aggregated `PopulationGroupCount`
rows, not a raw `list[DecisionEvent]` — the one concrete policy this
milestone ships (adverse impact ratio) only ever needs a `GROUP BY` count
per protected-attribute-value, which Postgres computes far more cheaply
than materializing every event in the window into Python and aggregating
there. See `population_engine/window.py` and `docs/milestones/M6.md`
§13.3's revised recommendation.

M8 (architecture §10, Evaluation Framework): this port needed no change
to generalize across a second concrete policy — `PopulationWindow` grew
one additive `parameters` field instead, carrying a binding's
admin-configured overrides the same way `classification_snapshot`
already carries computed context. See `docs/milestones/M8.md` §4.1/§4.3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from gov_platform.schemas.population_finding import PopulationFinding


class PopulationGroupCount(BaseModel):
    """One `(attribute_name, attribute_value)` group's outcome counts
    within a window — the unit adverse-impact-ratio-style metrics need,
    computed by one SQL `GROUP BY`, not assembled from row-level
    `DecisionEvent`s."""

    model_config = ConfigDict(frozen=True)

    attribute_name: str
    attribute_value: str
    total_count: int
    favorable_outcome_count: int


class PopulationWindow(BaseModel):
    """One system's decisions over one time window — the unit a
    `PopulationPolicy` evaluates. Built by `population_engine/window.py`,
    which reads `decision_events.protected_attribute_refs` for values and
    `protected_attribute_rules` for which attribute names are `DIRECT`
    (see `docs/milestones/M6.md` §4.2/§13.15) — not persisted itself.

    `classification_snapshot` is exactly what was read to decide which
    attribute names to group by, carried forward so the eventual
    `PopulationFinding` is self-contained and independently reproducible
    even if `protected_attribute_rules` changes later — see
    `docs/milestones/M6.md` §13.16.

    `parameters` (M8, architecture §10) is the binding's admin-configured
    overrides for whichever policy evaluates this window (e.g.
    `threshold`, `minimum_group_size`, `z_critical`) — empty by default,
    attached by `run_policies.py` from the `PopulationPolicyBinding`
    immediately before calling `evaluate()`, never by
    `population_engine/window.py`'s `build_population_window`, which
    stays generic and binding-unaware. See `docs/milestones/M8.md`
    §4.3/§13.2 for why this lives here rather than widening
    `PopulationPolicy.evaluate`'s own signature.
    """

    model_config = ConfigDict(frozen=True)

    system_id: str
    window_start: datetime
    window_end: datetime
    group_counts: list[PopulationGroupCount]
    classification_snapshot: dict[str, str]
    parameters: dict[str, float] = Field(default_factory=dict)


class PopulationPolicy(ABC):
    """A single population-level governance rule, evaluated against one
    `PopulationWindow`."""

    population_policy_id: str
    version: str

    @abstractmethod
    def evaluate(self, window: PopulationWindow) -> PopulationFinding:
        """Evaluate one `PopulationWindow` and return one `PopulationFinding`."""
        raise NotImplementedError
