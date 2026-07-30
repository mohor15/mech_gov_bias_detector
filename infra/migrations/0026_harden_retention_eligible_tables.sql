-- Retention-eligible table hardening -- architecture §13, M11. Kept
-- deliberately separate from migration 0025's much higher-risk lockdown:
-- these two tables share a low-risk profile (bounded, low-write-volume
-- operational tables -- shadow comparison output and per-decision
-- attribute resolutions, not decision_events-scale ingestion traffic), so
-- their own privilege tightening and their own new indexes belong
-- together, safe to apply at any time, no maintenance window required.
-- See docs/milestones/M11.md §5.2/§5.3/§6/§8.
--
-- Retention-eligible tables keep INSERT/SELECT for the running app, but
-- lose DELETE (and UPDATE, since neither is ever updated post-insert
-- either) -- only the retention tool's own, separately-credentialed
-- connection may ever delete a row from either (see
-- docs/milestones/M11.md §5.2/§5.3). This is a deliberate tightening
-- beyond what migrations 0009/0010 originally granted, not a correction of
-- a defect in those milestones -- neither table had a retention mechanism
-- yet to reserve deletion capability for at the time.
REVOKE UPDATE, DELETE ON shadow_findings FROM gov_platform_app;
REVOKE UPDATE, DELETE ON protected_attribute_resolutions FROM gov_platform_app;

-- Supports "delete rows older than a given cutoff timestamp" for the new
-- retention CLI (retention/purge_expired_records.py) -- neither table has
-- an index shaped for a time-bounded scan today, the identical situation
-- M6 §6/M7 §6 were each in for their own new query patterns.
--
-- NOTE: this file is applied via SQLAlchemy's text(), which treats a
-- colon immediately followed by a word, anywhere in the string (including
-- inside a SQL comment), as a bind-parameter placeholder -- see migration
-- 0017's own identical warning, first found and fixed at M7. Never write
-- that punctuation mark followed directly by an identifier in any
-- migration file's comments (spell out "a given timestamp"/"a given
-- cutoff" instead), or db.migrate.apply_migrations raises "a value is
-- required for bind parameter" before the DDL ever runs.
CREATE INDEX idx_shadow_findings_evaluated_at
    ON shadow_findings (evaluated_at);
CREATE INDEX idx_protected_attribute_resolutions_resolved_at
    ON protected_attribute_resolutions (resolved_at);
