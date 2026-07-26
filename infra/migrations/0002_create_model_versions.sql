-- One row per (system, version) pair. Architecture §16.1: ModelVersion is
-- what a DecisionEvent actually links to, not System directly.
CREATE TABLE model_versions (
    id          TEXT PRIMARY KEY,
    system_id   TEXT NOT NULL REFERENCES systems(id),
    version     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (system_id, version)
);
