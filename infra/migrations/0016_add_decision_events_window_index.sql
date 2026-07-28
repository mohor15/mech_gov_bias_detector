-- Supports the one new read pattern M6 introduces: "this system's
-- decision_events in this time window" (population_engine/window.py),
-- joining decision_events -> model_versions -> systems. Without this,
-- that join table-scans decision_events at any real volume -- elevated
-- from "worth considering" to a concrete requirement during the
-- hostile-review pass, see docs/milestones/M6.md §6/§12.
CREATE INDEX idx_decision_events_model_version_occurred_at
    ON decision_events (model_version_id, occurred_at);
