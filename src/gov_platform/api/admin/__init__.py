"""Admin API — architecture §15.

System registration (M1) and the plugin lifecycle registry —
register/list/get/promote an `Adapter`/`Policy` (M3) — live here. M4's
policy plurality needed no new admin surface: an adapter's governing
policies were a fixed, code-defined tuple, administered through the same
plugin registry endpoints regardless of how many policy families existed.

M5 adds two real new surfaces: Policy Bindings
(`policy_bindings.py` — which policy families govern which adapter,
`create`/`list`/`get`/`activate`/`deactivate`, replacing that code-defined
tuple with a database fact) and Protected Attribute Rules
(`protected_attribute_rules.py` — the DB-backed classification ruleset
`EvidenceStore`'s resolution path consults, `create`/`list`/`get`, no
lifecycle to promote). Neither loads new code — both manage facts about
already-deployed `Adapter`/`Policy` implementations, the same boundary the
plugin registry draws. Domain/jurisdiction-*keyed* bindings (a richer
binding than adapter-keyed) remain deferred — see
`docs/milestones/M5.md` §13.1.

M6 adds two more: Population Policy Bindings
(`population_policy_bindings.py` — which `PopulationPolicy` evaluates
which `System`, `system_id`-keyed, not `adapter_id`-keyed — see
`docs/milestones/M6.md` §13.8) and Population Findings
(`population_findings.py` — read-only, `list`/`get` only; a population
finding is only ever produced by `population_engine/run_policies.py`'s
batch job, never through this API). Still no authentication anywhere,
including these — see `docs/milestones/M6.md` §13.14 for why this gap is
flagged more sharply at M6 than at any prior milestone.

M9 adds Human Review Workflow's two surfaces: Verdict Reviews
(`verdict_reviews.py`) and Population Finding Reviews
(`population_finding_reviews.py`) — `list`/`get`/`claim`/`release`/`resolve`
for a `VerdictReview`/`PopulationFindingReview`, the workflow state that
finally gives an `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` `Verdict` (M5) or a
`FLAGGED` `PopulationFinding` (M6/M8) somewhere to go. Neither loads new
code or computes a new result — both manage workflow state *about* an
already-computed, already-immutable subject, the same boundary every prior
Admin API in this module draws. See `docs/milestones/M9.md` §3.7 for the
full endpoint shape, including why `claim`/`release`/`resolve` translate a
repository-raised `ValueError` into a `409` explicitly rather than letting
it fall through to `api/app.py`'s global handler (which defaults to
`422`). Ten new endpoints, still no authentication — the sharpest version
of this gap yet, since this is the first milestone where an
unauthenticated caller can fabricate a specific, named person's
professional judgment about a real bias finding (`docs/milestones/M9.md`
§7).
"""
