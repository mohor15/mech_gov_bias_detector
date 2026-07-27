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


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
