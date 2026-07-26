-- One row per GovernanceVerdict. `status` is the M0/architecture-§8.2
-- two-value placeholder (ALLOW/FLAGGED) as a plain TEXT column, not a SQL
-- ENUM — enum values changing at M5 would otherwise require an ALTER TYPE
-- migration for no behavioral benefit today.
CREATE TABLE verdicts (
    id                  TEXT PRIMARY KEY,
    decision_event_id   TEXT NOT NULL REFERENCES decision_events(id),
    status              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL
);
