"""Policy plugin surface — architecture §7.

M0 defines the port (`Policy`); it now has three reference implementations
(`AlwaysAllowPolicy`, `DirectAttributeInInputsPolicy`,
`HighDebtRatioGatePolicy`). The promotion lifecycle is M3; policy
plurality and disagreement surfacing (`GovernanceEngine` running more than
one of these against a single event) is M4.

Population-level (batch) policies are a deliberately separate, parallel
port — `population_engine.PopulationPolicy` (M6), not a widened `Policy`
here: `Policy.evaluate`'s single-event, `Finding`-per-`decision_event_id`
contract is structurally incompatible with an aggregate result over many
decisions. See `population_engine/base.py` and `docs/milestones/M6.md`
§9/§13.3. A general, pluggable population-metrics *framework* (as opposed
to the one concrete policy M6 ships) remains M8.
"""
