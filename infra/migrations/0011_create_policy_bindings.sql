-- Policy Bindings -- architecture §7/§8, M5. Dynamic, admin-managed
-- replacement for the static, code-defined Adapter.governing_policy_ids
-- tuple M3/M4 built: which policy families govern an adapter's events is
-- now a database fact, changeable without a redeploy. Keyed by adapter_id,
-- not by System.domain/jurisdiction -- see docs/milestones/M5.md §13.1 for
-- why the richer domain/jurisdiction-keyed design is deferred until a
-- second real domain exists to validate it against.
--
-- lifecycle_state is ACTIVE/INACTIVE, deliberately not a reuse of
-- plugin_registrations' DRAFT/SHADOW/PRODUCTION -- see §13.2: a binding
-- answers "does this already-trusted policy apply here", an orthogonal
-- question to "is this policy's code trusted to run at all", which
-- plugin_registrations already fully owns.
--
-- severity lives here, not on Policy (see §13.5): how serious a violation
-- is in the context of a specific adapter is an administrative judgment,
-- not a property of the policy's own code.
CREATE TABLE policy_bindings (
    id              TEXT PRIMARY KEY,
    adapter_id      TEXT NOT NULL,
    policy_id       TEXT NOT NULL,
    severity        TEXT NOT NULL,   -- 'LOW' | 'MEDIUM' | 'HIGH'
    lifecycle_state TEXT NOT NULL,   -- 'ACTIVE' | 'INACTIVE'
    created_at      TIMESTAMPTZ NOT NULL,

    UNIQUE (adapter_id, policy_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON policy_bindings TO gov_platform_app;
