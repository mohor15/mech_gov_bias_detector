-- Protected Attribute Resolution Service output (architecture §4.3, M2).
-- One row per (Decision Event, expected attribute) pair -- see
-- protected_attributes/resolver.py for what produces these rows and
-- schemas/protected_attribute.py for the domain model this mirrors.
-- Includes WITHHELD rows for attributes a domain expects but a given
-- event didn't supply, not just DIRECT/PROXIED ones that were present.
--
-- Derived, reconstructable data (re-running the resolver over the same
-- Decision Event reproduces it) -- not part of the hash-chained evidence
-- ledger. Unlike evidence_chain (migration 0008), this table does not get
-- UPDATE/DELETE revoked from gov_platform_app: ordinary application-level
-- discipline (no code path ever calls UPDATE/DELETE on it) is the right
-- amount of enforcement here, since reproducibility doesn't require the
-- same tamper-evidence guarantee hash-chaining exists to provide. See
-- docs/milestones/M2.md §11.6 for the full reasoning.
CREATE TABLE protected_attribute_resolutions (
    id                  TEXT PRIMARY KEY,
    decision_event_id   TEXT NOT NULL REFERENCES decision_events(id),
    attribute_name      TEXT NOT NULL,
    classification      TEXT NOT NULL,
    proxy_basis         TEXT,
    resolved_at         TIMESTAMPTZ NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON protected_attribute_resolutions TO gov_platform_app;
