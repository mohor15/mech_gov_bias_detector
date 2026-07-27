-- Protected-attribute classification rules -- architecture §4.3, M5.
-- Dynamic, admin-managed replacement for
-- protected_attributes/classification.py's static _RULES_BY_DOMAIN dict.
--
-- Consumed by EvidenceStore's resolution path only (via
-- ProtectedAttributeResolver's optional DB-backed mode). Deliberately NOT
-- consumed by DirectAttributeInInputsPolicy, which keeps reading the
-- static, in-code ruleset -- a named, temporary divergence, not an
-- oversight. See docs/milestones/M5.md §13.9 for the full reasoning: a
-- Policy has always been constructed with zero arguments, and giving one
-- database access to consult this table would be a real Policy port
-- change this milestone deliberately does not make.
CREATE TABLE protected_attribute_rules (
    id             TEXT PRIMARY KEY,
    domain         TEXT NOT NULL,
    attribute_name TEXT NOT NULL,
    classification TEXT NOT NULL,   -- 'DIRECT' | 'PROXY'
    proxy_of       TEXT,            -- set iff classification = 'PROXY'
    created_at     TIMESTAMPTZ NOT NULL,

    UNIQUE (domain, attribute_name)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON protected_attribute_rules TO gov_platform_app;
