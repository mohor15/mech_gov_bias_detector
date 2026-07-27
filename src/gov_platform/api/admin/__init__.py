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
"""
