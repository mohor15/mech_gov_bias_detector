"""Admin API — architecture §15.

System registration (M1) and the plugin lifecycle registry —
register/list/get/promote an `Adapter`/`Policy` (M3) — live here. M4's
policy plurality needed no new admin surface: an adapter's governing
policies are a fixed, code-defined tuple (like its own `adapter_id`/
`version`), not a runtime binding — each policy in that tuple is
administered through the same plugin registry endpoints regardless of how
many policy families exist. Dynamic, admin-managed *binding* of policies
to domains/jurisdictions is M5's Policy Bindings, not this.
"""
