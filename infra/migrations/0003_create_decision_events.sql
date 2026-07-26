-- Normalized operational copy of a Decision Event, linked to a real
-- ModelVersion row rather than M0's bare system_id string.
--
-- id is DecisionEvent.event_id itself (not a separate surrogate key) and is
-- PRIMARY KEY here — a deliberate new constraint M0's single blob table
-- never enforced. Ingesting the same event_id twice is now a data-integrity
-- error, not a silently-accepted duplicate.
--
-- input_features / protected_attribute_refs / decision_output are stored as
-- JSON-serialized TEXT, matching M0's EvidenceStore convention of manual
-- json.dumps/json.loads rather than relying on a dialect-specific JSON
-- column type.
CREATE TABLE decision_events (
    id                          TEXT PRIMARY KEY,
    model_version_id            TEXT NOT NULL REFERENCES model_versions(id),
    decision_type               TEXT NOT NULL,
    subject_ref                 TEXT NOT NULL,
    occurred_at                 TIMESTAMPTZ NOT NULL,
    ingested_at                 TIMESTAMPTZ NOT NULL,
    input_features              TEXT NOT NULL,
    protected_attribute_refs    TEXT NOT NULL,
    decision_output             TEXT NOT NULL
);
