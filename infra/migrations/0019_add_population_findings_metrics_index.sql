-- Supports M7's "population finding counts by (population_policy_id,
-- outcome) since a given timestamp" governance-health metric AND the
-- per-binding staleness query (most recent evaluated_at per
-- population_policy_id/system_id, LEFT JOINed from
-- population_policy_bindings -- see docs/milestones/M7.md
-- §4.2/§6/§13.17 for why the join direction matters). (See migration
-- 0017's note on why this comment must never contain a colon directly
-- followed by a word.)
CREATE INDEX idx_population_findings_policy_system_evaluated_at
    ON population_findings (population_policy_id, system_id, evaluated_at);
