-- Relax population_policy_bindings' uniqueness to a partial index scoped
-- to ACTIVE -- architecture §10, M8. Traced from "parameters are
-- admin-configurable" (migration 0020) to "can an admin actually change
-- them": today, no -- the plain UNIQUE (system_id, population_policy_id)
-- constraint below (migration 0014) makes a binding's identity
-- permanent, blocking a second binding for the same pair even after the
-- first is deactivated. See docs/milestones/M8.md §4.4/§13.3/§13.19 for
-- the full reasoning, including why this is not simply "the same shape
-- plugin_registrations already uses" (that partial index was part of
-- its *original* migration 0010 -- this one is genuinely dropping and
-- replacing a constraint already enforced against real, live rows).
--
-- Safe for every existing row: the new partial index is strictly *less*
-- restrictive than the old plain one -- any row set satisfying "at most
-- one row per (system_id, population_policy_id), full stop" trivially
-- satisfies "at most one *ACTIVE* row per (system_id,
-- population_policy_id)".
--
-- Plain CREATE UNIQUE INDEX, not CONCURRENTLY: db/migrate.py's
-- apply_migrations wraps every migration file in one transaction, and
-- CREATE INDEX CONCURRENTLY is illegal inside a transaction block --
-- verified against the runner's actual code, not assumed. Accepted
-- deliberately: population_policy_bindings is bounded, low-write-volume
-- admin configuration (one row per real (system, population policy)
-- pair, no request-path or per-decision write traffic), so the brief
-- write lock this incurs is a non-event in practice. Apply during a
-- low-admin-activity window as a documented precaution regardless.
--
-- Ships together with db/repositories/population_policy_binding.py's new
-- get_active_by_identity method and api/admin/population_policy_bindings.py's
-- matching conflict-check change -- this schema change alone does not
-- make a binding's parameters actually changeable (§13.19).
ALTER TABLE population_policy_bindings
    DROP CONSTRAINT population_policy_bindings_system_id_population_policy_id_key;

CREATE UNIQUE INDEX one_active_population_policy_binding_per_system
    ON population_policy_bindings (system_id, population_policy_id)
    WHERE lifecycle_state = 'ACTIVE';
