"""Governance Engine — architecture §8.

M4 gave this real policy plurality (every `Policy` it's constructed with
runs, and their Findings aggregate via any-`FLAGGED`-wins). M5: the
aggregation is now severity-driven — the highest `PolicySeverity` among
flagged findings decides which of the four `VerdictStatus` values applies
(`ALLOW` / `ALLOW_WITH_FLAG` / `ESCALATE_FOR_REVIEW` / `RECOMMEND_HOLD`).
Severity comes from each policy's Policy Binding
(`schemas/policy_binding.py`), resolved per adapter by
`api/ingestion/routes.py` — see `governance_engine.engine` for the precise
mechanics. Cryptographic signing of evidence records is also M5, but lives
in `audit/signing.py`, not here.
"""
