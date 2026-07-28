"""Population-level policy engine — architecture §7/§8, M6.

A `PopulationPolicy` evaluates many `DecisionEvent`s for one `System` over
one time window, not one event at a time — a genuinely different question
from `policy_engine.Policy`'s ("does this one decision violate a rule"),
not a widened version of it. See `population_engine/base.py` and
`docs/milestones/M6.md` §9/§13.3 for the full reasoning behind a new,
parallel port instead of reusing `Policy`/`Finding`/`GovernanceEngine`.

Evaluated by an explicitly-invoked batch job
(`population_engine/run_policies.py`), never inline with an ingestion
request — see `docs/milestones/M6.md` §13.4/§13.13.
"""
