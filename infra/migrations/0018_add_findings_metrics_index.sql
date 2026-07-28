-- Supports M7's "finding counts by (policy_id, outcome) since a given
-- timestamp" governance-health metric (architecture §9) -- see
-- docs/milestones/M7.md §4.2/§6. (See migration 0017's note on why this
-- comment must never contain a colon directly followed by a word --
-- db.migrate applies this file via SQLAlchemy's text(), which parses
-- that as a bind parameter even inside a SQL comment.)
CREATE INDEX idx_findings_evaluated_at_policy_id_outcome
    ON findings (evaluated_at, policy_id, outcome);
