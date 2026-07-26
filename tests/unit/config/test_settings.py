from __future__ import annotations

from gov_platform.config.settings import Settings, get_settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.APP_NAME == "AI Governance Platform"
    assert settings.DATABASE_URL.startswith("postgresql")


def test_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_LOG_LEVEL", "DEBUG")
    assert Settings().LOG_LEVEL == "DEBUG"


def test_database_url_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    assert Settings().DATABASE_URL == "postgresql+psycopg://test:test@localhost/test"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
