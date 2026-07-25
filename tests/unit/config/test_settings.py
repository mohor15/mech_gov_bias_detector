from __future__ import annotations

from pathlib import Path

from gov_platform.config.settings import Settings, get_settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.APP_NAME == "AI Governance Platform"
    assert Path("data/evidence.db") == settings.EVIDENCE_DB_PATH


def test_env_var_override(monkeypatch) -> None:
    monkeypatch.setenv("GOV_PLATFORM_LOG_LEVEL", "DEBUG")
    assert Settings().LOG_LEVEL == "DEBUG"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
