-- Plugin registry lifecycle state (architecture §6, M3). Records which
-- already-deployed Adapter/Policy implementation (see plugins/registry.py
-- for the in-process catalog of what code exists at all) is currently
-- draft/shadow/production -- an operational, admin-controlled fact, not a
-- code fact. See schemas/plugin_registration.py for the domain model this
-- mirrors and docs/milestones/M3.md for the full design.
CREATE TABLE plugin_registrations (
    id              TEXT PRIMARY KEY,
    plugin_type     TEXT NOT NULL,   -- 'ADAPTER' | 'POLICY'
    plugin_id       TEXT NOT NULL,
    version         TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,   -- 'DRAFT' | 'SHADOW' | 'PRODUCTION'
    registered_at   TIMESTAMPTZ NOT NULL,
    promoted_at     TIMESTAMPTZ,

    UNIQUE (plugin_type, plugin_id, version)
);

-- At most one PRODUCTION version per (plugin_type, plugin_id) at a time --
-- many DRAFT/SHADOW candidates may coexist, but exactly one implementation
-- may actually govern real decisions for a given plugin_id. Enforced here,
-- not only in application code -- the same discipline M1's evidence
-- append-only guarantee established (docs/milestones/M3.md §13.6).
CREATE UNIQUE INDEX one_production_version_per_plugin
    ON plugin_registrations (plugin_type, plugin_id)
    WHERE lifecycle_state = 'PRODUCTION';

-- A SHADOW-state policy's Finding, kept structurally separate from
-- `findings` (which only ever holds Findings that actually contributed to
-- a served Verdict) so a shadow evaluation can never be mistaken for one
-- that did, and so VerdictRepository's join back to `findings` can never
-- accidentally pick one up. See docs/milestones/M3.md §13.3.
CREATE TABLE shadow_findings (
    id                     TEXT PRIMARY KEY,
    decision_event_id      TEXT NOT NULL REFERENCES decision_events(id),
    plugin_registration_id TEXT NOT NULL REFERENCES plugin_registrations(id),
    outcome                TEXT NOT NULL,
    confidence             DOUBLE PRECISION NOT NULL,
    rationale              TEXT NOT NULL,
    metric_values          TEXT NOT NULL,
    evaluated_at           TIMESTAMPTZ NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON plugin_registrations, shadow_findings TO gov_platform_app;
