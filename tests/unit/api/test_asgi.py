"""Confirms the uvicorn entrypoint actually builds a working app.

Runs in a temp working directory so this test — the one place `create_app()`
runs with zero overrides — cannot write a stray `data/evidence.db` into the
repository itself, which is exactly the failure mode this file exists to
prevent module (see `api.asgi` docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_asgi_app_is_healthy(isolated_cwd: Path) -> None:
    from gov_platform.api.asgi import app  # imported here: construction happens on import

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    assert (isolated_cwd / "data" / "evidence.db").exists()
