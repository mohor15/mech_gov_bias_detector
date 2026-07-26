"""Policy plugin surface — architecture §7.

M0 defines the port (`Policy`); it now has three reference implementations
(`AlwaysAllowPolicy`, `DirectAttributeInInputsPolicy`,
`HighDebtRatioGatePolicy`). The promotion lifecycle is M3; policy
plurality and disagreement surfacing (`GovernanceEngine` running more than
one of these against a single event) is M4. Population-level (batch)
policies remain M6/M8 — deliberately not here.
"""
