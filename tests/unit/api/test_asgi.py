"""Confirms the uvicorn entrypoint actually builds a working app.

M1 update: M0's version of this test asserted that importing `api.asgi`
created a stray `data/evidence.db` SQLite file and ran in an isolated CWD to
contain that side effect. Neither applies anymore — `EvidenceStore` is
Postgres-only now and its construction is lazy (see its module docstring),
so importing `api.asgi` with zero overrides touches neither the filesystem
nor the network. This test now asserts the *absence* of any stray file as
the direct, positive confirmation of that laziness, alongside the original
liveness check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_asgi_app_is_healthy_and_touches_no_local_state(isolated_cwd: Path) -> None:
    from gov_platform.api.asgi import app  # imported here: construction happens on import

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    # Confirms EvidenceStore's construction stayed lazy: no local file of
    # any kind should exist just from building and health-checking the app.
    assert list(isolated_cwd.iterdir()) == []
