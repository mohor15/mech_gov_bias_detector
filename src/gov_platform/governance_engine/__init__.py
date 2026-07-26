"""Governance Engine — architecture §8.

M4: runs every `Policy` it's constructed with and aggregates their
Findings (any `FLAGGED` makes the Verdict `FLAGGED`) — real policy
plurality and disagreement surfacing, per `docs/milestones/M4.md`. Policy
Bindings, escalation rules, and cryptographic signing remain M5 — see
`governance_engine.engine` for the precise boundary.
"""
