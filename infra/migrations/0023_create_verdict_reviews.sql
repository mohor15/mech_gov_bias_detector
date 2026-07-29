-- Verdict Reviews -- architecture §12, M9 (Human Review Workflow). One
-- review record per GovernanceVerdict whose status is ESCALATE_FOR_REVIEW
-- or RECOMMEND_HOLD -- an ESCALATE_FOR_REVIEW verdict that says "review
-- me" finally has somewhere to go (see docs/milestones/M5.md's own naming
-- of this gap, closed four milestones later).
--
-- verdict_id references verdicts(id), not a copy of the verdict itself:
-- review state is ordinary, mutable workflow metadata *about* an
-- already-signed, already-chained evidentiary record -- it must never
-- touch, and is never touched by, the Verdict/evidence_chain it
-- references. ON DELETE RESTRICT is explicit rather than left to
-- Postgres's implicit default, matching this schema's own convention of
-- spelling out every constraint's intent: nothing in this codebase
-- currently deletes a verdicts row, so this enforces an invariant rather
-- than changing behavior.
--
-- status is OPEN | IN_REVIEW | RESOLVED. RESOLVED is terminal for this
-- row only, not for the verdict it references -- a resolved review can be
-- superseded by a *new* row (never a mutation of this one), which is why
-- the uniqueness constraint below is a partial index scoped to
-- non-RESOLVED rows, not a plain UNIQUE (verdict_id). A plain UNIQUE
-- constraint here would have reproduced, in a brand-new table, the exact
-- defect migration 0022 already fixed once for
-- population_policy_bindings: a constraint that is fine the day it ships
-- but permanently forecloses a legitimate future need (reopening a
-- previously-resolved review) the moment one appears.
--
-- resolution ('CONFIRMED' | 'DISMISSED') and resolution_notes are set
-- only when status becomes RESOLVED; reviewer and claimed_at are set only
-- when status becomes IN_REVIEW, and cleared again on release back to
-- OPEN.
--
-- Ordinary GRANT privileges, not evidence_chain's/population_findings'
-- lockdown: this is live, legitimate workflow state (is this review open,
-- claimed, or resolved), not computed governance output itself -- the
-- Verdict it references remains exactly as immutable as before this
-- migration.
CREATE TABLE verdict_reviews (
    id                TEXT PRIMARY KEY,
    verdict_id        TEXT NOT NULL REFERENCES verdicts(id) ON DELETE RESTRICT,
    status            TEXT NOT NULL,   -- 'OPEN' | 'IN_REVIEW' | 'RESOLVED'
    reviewer          TEXT,
    resolution        TEXT,            -- 'CONFIRMED' | 'DISMISSED', set only at RESOLVED
    resolution_notes  TEXT,
    created_at        TIMESTAMPTZ NOT NULL,
    claimed_at        TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ
);

-- At most one *active* (non-RESOLVED) review per verdict at a time --
-- never "ever, full stop". See this file's own header comment above for
-- why a plain UNIQUE (verdict_id) would have been the wrong constraint.
CREATE UNIQUE INDEX one_open_verdict_review_per_verdict
    ON verdict_reviews (verdict_id)
    WHERE status != 'RESOLVED';

-- Supports the review-list endpoint's primary filter
-- (GET /v1/admin/verdict-reviews?status=).
CREATE INDEX idx_verdict_reviews_status ON verdict_reviews (status);

GRANT SELECT, INSERT, UPDATE, DELETE ON verdict_reviews TO gov_platform_app;
