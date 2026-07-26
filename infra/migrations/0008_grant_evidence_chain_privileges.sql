-- DB-privilege-enforced append-only, per architecture §13 and the M1
-- acceptance criterion: "an attempted UPDATE/DELETE against the evidence
-- tables is rejected at the DB privilege level." One application role gets
-- full DML on the operational tables (systems, model_versions,
-- decision_events, findings, verdicts, verdict_findings) but only
-- INSERT + SELECT on evidence_chain specifically — Postgres grants are
-- per-table, so this needs no second connection or role.
--
-- gov_platform_app is created if it doesn't already exist so this migration
-- is safe to re-run and safe to apply to a fresh database where the
-- deployment hasn't provisioned the role yet. Created NOLOGIN, with no
-- password: this migration is checked into version control and must never
-- carry a credential. Enabling the role to actually authenticate (LOGIN +
-- a real password) is a separate, deliberately out-of-band step — a DBA's
-- ops task in a real deployment (secret-managed), or
-- infra/ci/setup_test_role.py for this repo's ephemeral CI database.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gov_platform_app') THEN
        CREATE ROLE gov_platform_app NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON systems, model_versions, decision_events, findings, verdicts, verdict_findings
    TO gov_platform_app;

GRANT SELECT, INSERT ON evidence_chain TO gov_platform_app;
REVOKE UPDATE, DELETE ON evidence_chain FROM gov_platform_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gov_platform_app;
