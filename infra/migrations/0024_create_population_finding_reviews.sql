-- Population Finding Reviews -- architecture §12, M9 (Human Review
-- Workflow). One review record per PopulationFinding whose outcome is
-- FLAGGED, from either population policy (adverse-impact-ratio or
-- disparity-significance-test) -- identical shape to migration 0023's
-- verdict_reviews, kept as a separate table rather than one polymorphic
-- table for the same reason PopulationFinding is a separate type from
-- Finding in the first place: a review of one is not interchangeable with
-- a review of the other, and a single subject_id column could never carry
-- a real foreign key to two different parent tables.
--
-- population_finding_id references population_findings(id). ON DELETE
-- RESTRICT is explicit for the same reason migration 0023 states it
-- explicitly: nothing in this codebase deletes a population_findings row
-- (that table is append-only at the database-privilege level, migration
-- 0015), so this enforces an invariant rather than changing behavior.
--
-- The partial unique index (not a plain UNIQUE) and ordinary GRANT
-- privileges mirror migration 0023's own reasoning exactly -- see that
-- file's header comment.
CREATE TABLE population_finding_reviews (
    id                     TEXT PRIMARY KEY,
    population_finding_id  TEXT NOT NULL REFERENCES population_findings(id) ON DELETE RESTRICT,
    status                 TEXT NOT NULL,   -- 'OPEN' | 'IN_REVIEW' | 'RESOLVED'
    reviewer               TEXT,
    resolution             TEXT,            -- 'CONFIRMED' | 'DISMISSED', set only at RESOLVED
    resolution_notes       TEXT,
    created_at             TIMESTAMPTZ NOT NULL,
    claimed_at             TIMESTAMPTZ,
    resolved_at            TIMESTAMPTZ
);

-- At most one *active* (non-RESOLVED) review per population finding at a
-- time -- see migration 0023's header comment for the full reasoning.
CREATE UNIQUE INDEX one_open_population_finding_review_per_finding
    ON population_finding_reviews (population_finding_id)
    WHERE status != 'RESOLVED';

-- Supports the review-list endpoint's primary filter
-- (GET /v1/admin/population-finding-reviews?status=).
CREATE INDEX idx_population_finding_reviews_status ON population_finding_reviews (status);

GRANT SELECT, INSERT, UPDATE, DELETE ON population_finding_reviews TO gov_platform_app;
