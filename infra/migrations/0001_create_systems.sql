-- System inventory (architecture §16.1). IDs are application-generated UUID
-- strings (uuid4, hex), consistent with every other identifier in this
-- codebase since M0 — no DB-side default generator, so this file stays
-- portable DDL with no dialect-specific ID function.
CREATE TABLE systems (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    domain      TEXT,
    risk_tier   TEXT,
    owner       TEXT,
    created_at  TIMESTAMPTZ NOT NULL
);
