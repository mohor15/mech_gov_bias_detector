"""Explicit, first-party plugin discovery — architecture §6, M3.

`register_adapter`/`register_policy` run as an import-time side effect,
so something has to actually import each plugin module before the
registry knows about it. This module is that "something" — a hand-
maintained list of imports, not filesystem scanning or dynamic module
loading (see `docs/milestones/M3.md` §13.2: discovery means "the registry
becomes aware of already-deployed code," not "arbitrary code gets loaded
from outside this codebase").

Adding a new first-party adapter or policy means adding one import line
here — not touching `api/app.py`'s composition root, which is the actual
"without modifying the composition root" guarantee M3 commits to.
"""

from __future__ import annotations

from gov_platform.adapters import credit_scorecard as _credit_scorecard  # noqa: F401
from gov_platform.adapters import synthetic as _synthetic  # noqa: F401
from gov_platform.policy_engine.policies import always_allow as _always_allow  # noqa: F401
from gov_platform.policy_engine.policies import (  # noqa: F401
    direct_attribute_in_inputs as _direct_attribute_in_inputs,
)
from gov_platform.policy_engine.policies import (  # noqa: F401
    high_debt_ratio_gate as _high_debt_ratio_gate,
)


def bootstrap_plugins() -> None:
    """No-op: importing this module already ran every registration
    decorator above. Calling this function from `api/app.py` makes *when*
    that happens explicit and gives static analysis/readers one obvious
    call site, rather than relying on import-order side effects alone."""
