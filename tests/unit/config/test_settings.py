from __future__ import annotations

from gov_platform.config.settings import Settings, get_settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.APP_NAME == "AI Governance Platform"
    assert settings.DATABASE_URL.startswith("postgresql")


def test_field_encryption_key_defaults_to_unset() -> None:
    # M11: encryption is opt-in, off by default -- no ephemeral fallback,
    # unlike SIGNING_PRIVATE_KEY. See docs/milestones/M11.md §5.1/§12.4.
    assert Settings().FIELD_ENCRYPTION_KEY is None


def test_field_encryption_key_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_FIELD_ENCRYPTION_KEY", "some-fernet-key")
    assert Settings().FIELD_ENCRYPTION_KEY == "some-fernet-key"


def test_retention_days_default_to_unset_no_numeric_default() -> None:
    # M11: no sourced external standard exists for either period (unlike
    # the EEOC ratio or CFPB threshold) -- unset means "disabled", never a
    # guessed number. See docs/milestones/M11.md §5.2.
    settings = Settings()
    assert settings.RETENTION_DAYS_SHADOW_FINDINGS is None
    assert settings.RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS is None


def test_retention_days_env_var_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_RETENTION_DAYS_SHADOW_FINDINGS", "90")
    monkeypatch.setenv("GOV_PLATFORM_RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS", "365")

    settings = Settings()

    assert settings.RETENTION_DAYS_SHADOW_FINDINGS == 90
    assert settings.RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS == 365


def test_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_LOG_LEVEL", "DEBUG")
    assert Settings().LOG_LEVEL == "DEBUG"


def test_database_url_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    assert Settings().DATABASE_URL == "postgresql+psycopg://test:test@localhost/test"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
