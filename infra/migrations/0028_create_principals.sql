-- Principals -- architecture (no numbered section; see docs/milestones/M13.md
-- Sourcing note), M13 (Authentication & Authorization). One row per
-- registered caller (human or machine): a name, a role from a small fixed
-- set, and one opaque bearer credential, stored only as a one-way SHA-256
-- digest (see access/tokens.py) -- the plaintext token is never persisted
-- anywhere, only shown once, at creation time, by access/create_principal.py.
--
-- role is plain TEXT, no CHECK constraint -- matches every other
-- enum-backed column in this schema (verdicts.status, findings.outcome,
-- verdict_reviews.status/resolution, plugin_registrations.plugin_type),
-- all validated at the Pydantic layer only (schemas/principal.py's
-- PrincipalRole), never duplicated at the DDL level. A CHECK constraint
-- here would be the first in this schema's 27-migration history --
-- considered and declined during M13's own design review, see
-- docs/milestones/M13.md Revision note item 11.
--
-- Ordinary GRANT privileges, not evidence_chain's/population_findings'
-- lockdown: principals records *who currently has access*, live
-- operational state with no evidentiary weight -- the same privilege
-- class as plugin_registrations/policy_bindings/protected_attribute_rules/
-- population_policy_bindings/verdict_reviews/population_finding_reviews
-- (docs/milestones/M11.md §5.3's six-table classification). DELETE stays
-- granted for the same reason it stays granted on those six tables,
-- though PrincipalRepository.revoke (an UPDATE setting revoked_at) is the
-- only write path this codebase actually calls -- "never destroy, only
-- supersede", the same discipline already applied to a resolved
-- VerdictReview.
CREATE TABLE principals (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,   -- 'INGESTION' | 'REVIEWER' | 'ADMIN' | 'READ_ONLY'
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ
);

-- The one query pattern every authenticated request needs, at O(1):
-- already covered by the UNIQUE constraint's own implicit index above,
-- named here so a future reader doesn't add a redundant explicit one.
-- No index on `name` -- lookups are always by token hash, never by name
-- at request-authentication time; principals are bounded by real-world
-- registration activity, not per-request traffic (docs/milestones/M13.md §6).

GRANT SELECT, INSERT, UPDATE, DELETE ON principals TO gov_platform_app;
