-- The hash-chained evidence ledger — same shape and hashing semantics as
-- M0's SQLite `evidence_records` table (sequence_number, previous_hash,
-- record_hash, payload snapshot), now on Postgres. `sequence_number` uses
-- Postgres's identity-column syntax, the one genuinely dialect-specific
-- piece of this schema (SQLite's AUTOINCREMENT syntax differs entirely) —
-- unavoidable for a strictly gapless, DB-assigned ordering.
--
-- Concurrent-writer safety does NOT come from a row lock here (see
-- EvidenceStore: `SELECT ... FOR UPDATE` was considered and rejected —
-- Postgres requires UPDATE privilege to take that lock, which would defeat
-- the REVOKE UPDATE below). It comes from a `pg_advisory_xact_lock` taken
-- in application code before the read-latest-hash-then-insert sequence,
-- which needs no table privileges at all. No seed/sentinel row is needed
-- for that reason, unlike an earlier draft of this migration.
CREATE TABLE evidence_chain (
    sequence_number     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_event_id   TEXT NOT NULL,
    verdict_id          TEXT NOT NULL,
    payload             TEXT NOT NULL,
    previous_hash       TEXT NOT NULL,
    record_hash         TEXT NOT NULL UNIQUE,
    recorded_at         TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_evidence_chain_decision_event_id ON evidence_chain (decision_event_id);
CREATE INDEX ix_evidence_chain_verdict_id ON evidence_chain (verdict_id);
