"""Application settings.

M0 scope: the handful of values the walking skeleton actually needs (app
metadata, log level, evidence store location). Governance thresholds, policy
bindings, and per-tenant configuration are introduced by later milestones as
the concepts they configure are built — adding empty placeholder fields for
them now would be speculative, not foundational.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration, sourced from environment variables and/or
    an optional `.env` file, both prefixed with ``GOV_PLATFORM_``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GOV_PLATFORM_", extra="ignore")

    APP_NAME: str = "AI Governance Platform"
    VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # SQLite file backing the M0 Evidence Store. Replaced by a Postgres
    # connection string in M1 (architecture §16) — kept as a simple path here
    # deliberately, so the M1 migration is a visible, reviewable change rather
    # than something hidden behind a premature abstraction today.
    EVIDENCE_DB_PATH: Path = Path("data/evidence.db")

    # Added during the M0 finalization review: the Ingestion API had no cap
    # on request body size, a real (if naive-client-only) DoS vector. 1MB is
    # generous for the small structured JSON this endpoint accepts. This is
    # a guard on the existing endpoint, not new capability — comprehensive
    # abuse protection (rate limiting, streaming byte-counting, reverse-proxy
    # limits) remains M13 deployment-hardening scope.
    MAX_REQUEST_BODY_BYTES: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
