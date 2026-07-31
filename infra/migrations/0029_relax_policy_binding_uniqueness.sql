-- Relax policy_bindings' uniqueness to a partial index scoped to
-- ACTIVE -- architecture §7/§8, M14. Closes docs/milestones/M8.md
-- §13.20's own disclosed, deliberately-deferred defect:
-- population_policy_bindings received this exact fix at M8
-- (migration 0022); policy_bindings never did. See
-- docs/milestones/M14.md §6/§8 for the full reasoning -- identical to
-- 0022's, applied to the sibling table it was always meant to also
-- cover.
--
-- Safe for every existing row, for the identical reason 0022 was: the
-- new partial index is strictly less restrictive than the plain
-- constraint it replaces -- any row set satisfying "at most one row per
-- (adapter_id, policy_id), full stop" trivially satisfies "at most one
-- *ACTIVE* row per (adapter_id, policy_id)".
--
-- Plain CREATE UNIQUE INDEX, not CONCURRENTLY -- identical reasoning to
-- 0022: db/migrate.py's apply_migrations wraps every migration file in
-- one transaction, and CREATE INDEX CONCURRENTLY is illegal inside a
-- transaction block. policy_bindings is bounded, low-write-volume admin
-- configuration (one row per real (adapter, policy) pair, no
-- request-path write traffic -- the request path only ever *reads*
-- policy_bindings via list_active_for_adapter), so the brief ACCESS
-- EXCLUSIVE lock this incurs is a non-event in practice, materially
-- different from migration 0025's own maintenance-window requirement.
--
-- Ships together with db/repositories/policy_binding.py's new
-- get_active_by_identity method and api/admin/policy_bindings.py's
-- matching conflict-check change -- this schema change alone does not
-- make a binding's severity actually changeable (see
-- docs/milestones/M14.md §5.1).
ALTER TABLE policy_bindings
    DROP CONSTRAINT policy_bindings_adapter_id_policy_id_key;

CREATE UNIQUE INDEX one_active_policy_binding_per_adapter
    ON policy_bindings (adapter_id, policy_id)
    WHERE lifecycle_state = 'ACTIVE';
