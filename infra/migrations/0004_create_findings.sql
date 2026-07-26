-- One row per Policy's evaluation of a Decision Event. In M0/M1 there is
-- always exactly one (AlwaysAllowPolicy); the table shape already supports
-- the many-per-event reality M4 introduces, since that's a data-model fact
-- from the frozen architecture (§16.1), not M4 behavior.
CREATE TABLE findings (
    id                  TEXT PRIMARY KEY,
    decision_event_id   TEXT NOT NULL REFERENCES decision_events(id),
    policy_id           TEXT NOT NULL,
    policy_version      TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    rationale           TEXT NOT NULL,
    metric_values       TEXT NOT NULL,
    evaluated_at        TIMESTAMPTZ NOT NULL
);
