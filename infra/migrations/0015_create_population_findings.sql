-- Population Findings -- architecture §13, M6. One PopulationPolicy's
-- result for one (system, window) pair. Never chained into evidence_chain
-- (see docs/milestones/M6.md §13.5) -- the hash chain's payload shape and
-- one-write-per-governed-decision append semantics don't fit an aggregate
-- result across many decisions with no single decision_event_id.
--
-- classification_snapshot records exactly which protected_attribute_rules
-- classifications (attribute_name -> 'DIRECT') were consulted to compute
-- this finding, as JSON. This is the reproducibility fix from the
-- hostile-review pass (§13.16): protected_attribute_rules is live,
-- admin-mutable data with no versioning of its own, unlike
-- population_policy_version, which already pins the policy's code
-- identity. Embedding the snapshot means a finding's meaning never
-- depends on protected_attribute_rules still agreeing with it later --
-- the same reason evidence_chain.payload embeds the full decision_event/
-- verdict rather than just their ids.
--
-- UNIQUE (population_policy_id, system_id, window_start, window_end): a
-- window is computed exactly once (§13.13) -- a duplicate insert (an
-- overlapping/retried run of python -m gov_platform.population.run_policies)
-- is a clean no-op, not a race that produces two disagreeing findings for
-- "the same" window.
--
-- Append-only at the database-privilege level, like evidence_chain --
-- corrected from this milestone's first design draft, which proposed
-- ordinary GRANT privileges here. A population_finding is computed
-- governance output, evidentiary in the same sense a Verdict is (§13.16):
-- "recomputing" a historical window under different rules must produce a
-- new row, never silently overwrite or reinterpret the original.
CREATE TABLE population_findings (
    id                          TEXT PRIMARY KEY,
    population_policy_id        TEXT NOT NULL,
    population_policy_version   TEXT NOT NULL,
    system_id                   TEXT NOT NULL REFERENCES systems(id),
    window_start                TIMESTAMPTZ NOT NULL,
    window_end                  TIMESTAMPTZ NOT NULL,
    outcome                     TEXT NOT NULL,   -- 'CLEAR' | 'FLAGGED'
    metric_values                TEXT NOT NULL,   -- JSON, matching every other table's convention
    classification_snapshot      TEXT NOT NULL,   -- JSON: attribute_name -> classification, as read at computation time
    rationale                    TEXT NOT NULL,
    evaluated_at                 TIMESTAMPTZ NOT NULL,
    signature                    TEXT,
    signing_key_id                TEXT,

    UNIQUE (population_policy_id, system_id, window_start, window_end)
);

GRANT SELECT, INSERT ON population_findings TO gov_platform_app;
REVOKE UPDATE, DELETE ON population_findings FROM gov_platform_app;
