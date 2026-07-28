-- Population Policy Bindings -- architecture §7/§8, M6. Which
-- PopulationPolicy evaluates which System's decisions -- system_id-keyed,
-- NOT adapter_id-keyed like policy_bindings (migration 0011). See
-- docs/milestones/M6.md §13.8: a population-level analysis is naturally
-- about a System's aggregate decisions across however many adapter
-- versions have produced them over time, not about one adapter's events.
-- Deliberately a separate table from policy_bindings -- different key,
-- different shape, different question, the same reasoning M5 already
-- applied to keep policy_bindings/protected_attribute_rules apart.
--
-- lifecycle_state is ACTIVE/INACTIVE, mirroring policy_bindings' own
-- (deliberately not plugin_registrations' DRAFT/SHADOW/PRODUCTION -- a
-- binding answers "does this already-trusted policy apply here", not "is
-- this policy's code trusted to run at all").
--
-- Ordinary GRANT privileges, not evidence_chain's/population_findings'
-- lockdown: this is live, legitimate admin config (which system a policy
-- currently applies to), not computed governance output -- see
-- docs/milestones/M6.md §6/§13.16.
CREATE TABLE population_policy_bindings (
    id                    TEXT PRIMARY KEY,
    system_id             TEXT NOT NULL REFERENCES systems(id),
    population_policy_id  TEXT NOT NULL,
    lifecycle_state       TEXT NOT NULL,   -- 'ACTIVE' | 'INACTIVE'
    created_at            TIMESTAMPTZ NOT NULL,

    UNIQUE (system_id, population_policy_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON population_policy_bindings TO gov_platform_app;
