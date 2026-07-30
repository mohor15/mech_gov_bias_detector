-- Privilege classification for the Evidence Store -- architecture §13, M11.
-- Closes docs/milestones/M9.md §9.5's disclosed gap: these six tables
-- write exactly once per governed decision (inside EvidenceStore.append's
-- single transaction) and are never updated or deleted by any existing
-- code path -- verified directly, not assumed. Matches evidence_chain's
-- (migration 0008) and population_findings' (migration 0015) own
-- privilege treatment. See docs/milestones/M11.md §5.3/§6/§8.
--
-- OPERATOR NOTE (see docs/milestones/M11.md §6/§8): GRANT/REVOKE on a
-- table takes an ACCESS EXCLUSIVE lock in PostgreSQL -- the same class of
-- lock ordinary ALTER TABLE DDL takes -- conflicting with every concurrent
-- statement against that table, including plain SELECT, and (per
-- PostgreSQL's lock-queue ordering) blocking new transactions that arrive
-- while it waits. decision_events specifically is touched by every single
-- ingestion request this platform serves. Apply this migration during a
-- planned, low-traffic maintenance window, the same operational discipline
-- any ACCESS-EXCLUSIVE-requiring DDL against a request-path table needs --
-- not silently assumed to be as cheap as an ordinary additive migration.
-- Kept as one transaction deliberately, not split per table: a partially
-- applied lockdown (some of the six tables locked, some not) is a worse,
-- more confusing intermediate state than a single, scheduled, atomic cutover.
REVOKE UPDATE, DELETE ON systems FROM gov_platform_app;
REVOKE UPDATE, DELETE ON model_versions FROM gov_platform_app;
REVOKE UPDATE, DELETE ON decision_events FROM gov_platform_app;
REVOKE UPDATE, DELETE ON findings FROM gov_platform_app;
REVOKE UPDATE, DELETE ON verdicts FROM gov_platform_app;
REVOKE UPDATE, DELETE ON verdict_findings FROM gov_platform_app;
