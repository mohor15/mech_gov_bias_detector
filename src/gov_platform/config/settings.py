"""Application settings.

M0 scope: the handful of values the walking skeleton actually needs (app
metadata, log level, evidence store location). Governance thresholds, policy
bindings, and per-tenant configuration are introduced by later milestones as
the concepts they configure are built — adding empty placeholder fields for
them now would be speculative, not foundational.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration, sourced from environment variables and/or
    an optional `.env` file, both prefixed with ``GOV_PLATFORM_``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GOV_PLATFORM_", extra="ignore")

    APP_NAME: str = "AI Governance Platform"
    VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # M1: replaces M0's EVIDENCE_DB_PATH (a SQLite file path), removed —
    # dead config once nothing points at a SQLite file anymore. This is the
    # app's own runtime connection string, expected to authenticate as the
    # restricted `gov_platform_app` role (see
    # infra/migrations/0008_grant_evidence_chain_privileges.sql), not as a
    # migration-privileged superuser/owner. Migrations use a separate,
    # more-privileged connection string passed directly to `db.migrate`'s
    # CLI — deliberately kept out of this settings model, since migration
    # credentials are an ops-time concern with different privileges than
    # the running app, not a runtime app dependency.
    DATABASE_URL: str = "postgresql+psycopg://gov_platform_app@localhost:5432/gov_platform"

    # Added during the M0 finalization review: the Ingestion API had no cap
    # on request body size, a real (if naive-client-only) DoS vector. 1MB is
    # generous for the small structured JSON this endpoint accepts. This is
    # a guard on the existing endpoint, not new capability — comprehensive
    # abuse protection (rate limiting, streaming byte-counting, reverse-proxy
    # limits) remains M13 deployment-hardening scope.
    MAX_REQUEST_BODY_BYTES: int = 1_000_000

    # M5: hex-encoded 32-byte Ed25519 private key seed, evidence records are
    # signed with (see audit/signing.py). `None` (the default) means "no
    # persistent key configured" — EvidenceStore falls back to a fresh,
    # process-local ephemeral key, which signs and verifies fine within one
    # process's lifetime (e.g. local dev, tests) but cannot be verified by a
    # separate process (a restart, or `verify_chain`'s CLI) since nothing
    # persists it. Real deployments must set this explicitly. A single
    # static key, no rotation, no KMS/HSM — a deliberate M5 scope boundary,
    # see docs/milestones/M5.md §13.8.
    SIGNING_PRIVATE_KEY: str | None = None
    SIGNING_KEY_ID: str = "default"

    # M11: a url-safe-base64-encoded 32-byte Fernet key
    # (`cryptography.fernet.Fernet.generate_key()`'s own output), application-
    # level-encrypting a fixed, named list of columns (see audit/encryption.py
    # and docs/milestones/M11.md §5.1) that are never filtered, compared, or
    # ordered by their own content in any SQL statement this codebase issues.
    # `None` (the default) means encryption is off: those columns are stored
    # and read as plaintext, exactly as every milestone before this one
    # already does. Deliberately diverging from `SIGNING_PRIVATE_KEY`'s own
    # precedent in two respects, both corrected/specified during this
    # milestone's own third hostile-review pass (see docs/milestones/M11.md
    # §5.1/§12.4/§12.17): (1) its encoding is Fernet's own base64 format, not
    # `SIGNING_PRIVATE_KEY`'s hex convention -- a raw hex string here raises
    # at first use, not silently; (2) there is no ephemeral, auto-generated
    # fallback when unset -- a fresh, per-process encryption key would
    # encrypt real data under a key that exists nowhere durable, losing
    # access to it on the next process restart, an unrecoverable,
    # self-inflicted data-loss bug a signing key's identical-looking fallback
    # does not share.
    FIELD_ENCRYPTION_KEY: str | None = None

    # M11: per-table retention windows (in days) for the two tables this
    # milestone classifies as retention-eligible -- shadow_findings and
    # protected_attribute_resolutions, the only tables in this schema that
    # are simultaneously non-evidentiary and not locked against deletion at
    # the database-privilege level (see docs/milestones/M11.md §5.2). `None`
    # (the default for both) means retention is disabled for that table --
    # retention/purge_expired_records.py's own CLI, invoked with no
    # configured window for a table, is a clean no-op for it, logged as
    # such. Deliberately no numeric default for either: unlike this
    # platform's other governance-sensitive constants (the EEOC four-fifths
    # ratio, the CFPB debt-to-income threshold, the Castaneda z-critical
    # convention), no external standard exists for how long a shadow-policy
    # comparison or a protected-attribute classification may legitimately
    # persist -- an operational/legal/business decision specific to a real
    # deployment, not one this platform can source a defensible number for
    # (see docs/milestones/M11.md §5.2, corrected during this milestone's
    # own hostile-review pass from an earlier, unsourced 90/365-day draft).
    RETENTION_DAYS_SHADOW_FINDINGS: int | None = None
    RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS: int | None = None

    # M13: gates whether every existing HTTP surface requires a `Principal`
    # credential (see api/dependencies.get_current_principal/require_role
    # and docs/milestones/M13.md §5.2/§13.1). This is this project's first
    # `bool` Settings field -- every other opt-in gate
    # (FIELD_ENCRYPTION_KEY, RETENTION_DAYS_*) instead uses the value's own
    # `None`-ness as the toggle. That pattern doesn't transfer here: unlike
    # a signing/encryption key, there is no single per-process secret for
    # this setting to key off of -- a principal's credential is
    # per-principal, provisioned into the `principals` table, not into
    # Settings at all -- so a bare boolean is the correct,
    # structurally-necessary departure (docs/milestones/M13.md §2, Revision
    # note item 14). Defaults to `True` (fail-closed) -- a deliberate,
    # disclosed break from FIELD_ENCRYPTION_KEY's own default-`False`
    # precedent, approved 2026-07-31 (docs/milestones/M13.md §13.1): every
    # other opt-in setting in this platform only weakens confidentiality or
    # retention hygiene when left off, while an unauthenticated caller can
    # fabricate ingestion events, silently deactivate a policy binding
    # governing real financial decisions, or falsely resolve a
    # bias-finding review under someone else's name -- the single sharpest
    # standing risk eleven consecutive milestone documents (M2 through M12)
    # named and deferred. No rotation, no KMS -- inherits SIGNING_PRIVATE_KEY's
    # (M5) identical scope boundary for the credential material it gates.
    AUTH_ENABLED: bool = True


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
