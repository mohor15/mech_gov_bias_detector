-- Cryptographic signing -- architecture §13, M5. Additive columns, not a
-- new table: one signature per evidence_chain row, 1:1, written at INSERT
-- time alongside record_hash. Nullable because M5's signing applies going
-- forward only -- see docs/milestones/M5.md §13.10: a signature asserts
-- "this deployment, holding this key, produced this record", which cannot
-- be legitimately asserted retroactively for M0-M4 rows that predate any
-- signing key's existence.
--
-- No new GRANT needed: gov_platform_app already has INSERT on evidence_chain
-- (migration 0008), which covers inserting values into these new columns
-- too. UPDATE/DELETE stay revoked -- a signature, like record_hash, can
-- only ever be set once, at insert time.
--
-- signing_key_id (not the raw key) is stored per record so a future
-- key-rotation milestone can tell which key verifies which historical
-- record without guessing.
ALTER TABLE evidence_chain ADD COLUMN signature TEXT;
ALTER TABLE evidence_chain ADD COLUMN signing_key_id TEXT;
