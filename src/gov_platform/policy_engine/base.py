"""The Policy port.

A `Policy` evaluates exactly one `DecisionEvent` and produces exactly one
`Finding` — a single-responsibility contract on purpose. Aggregating
multiple Findings into a Verdict is the `GovernanceEngine`'s job (§8), not
a Policy's; a Policy never sees another Policy's output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from gov_platform.schemas.decision_event import DecisionEvent
from gov_platform.schemas.finding import Finding


class Policy(ABC):
    """A single governance rule, evaluated against a single Decision Event."""

    policy_id: str
    version: str

    @abstractmethod
    def evaluate(self, event: DecisionEvent) -> Finding:
        """Evaluate one Decision Event and return one Finding."""
        raise NotImplementedError
