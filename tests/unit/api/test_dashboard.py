"""Compliance Dashboard — architecture §11, M10.

Testing scope follows `docs/milestones/M10.md` §8.5 exactly: does each
route return `200` with the expected static HTML; are the static JS/CSS
assets served with the right content-type; does the composition root wire
the dashboard without requiring a live database at construction time (the
same DB-free `create_app()` invariant every milestone since M3 has
preserved); does a dashboard packaging/construction failure degrade to "no
dashboard" rather than "no application" (§4.3/§8.6). The client-side
JavaScript's own rendering correctness is *not* covered here — an
accepted, explicitly named gap (§6/§8.5), verified manually instead.

None of these tests need `@requires_postgres`: `api_client` uses an
unreachable placeholder database URL when `POSTGRES_URL` isn't set (see
`tests/conftest.py`), and the dashboard touches no repository, no
`Engine`, no `app.state` entry at all -- this is itself part of what
`test_dashboard_routes_do_not_require_a_live_database` below confirms
directly, rather than merely relying on the tests running unmarked.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gov_platform.api import dashboard
from gov_platform.api.app import create_app
from gov_platform.config.settings import Settings


def test_overview_route_returns_the_shell_html(api_client: TestClient) -> None:
    response = api_client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Compliance Dashboard" in response.text


def test_overview_route_matches_exactly_without_a_redirect(test_settings: Settings) -> None:
    """Regression guard: `@router.get("/")` under `prefix="/dashboard"`
    registers the exact path `/dashboard/`, not `/dashboard` -- a bare
    `GET /dashboard` would then 307-redirect rather than match directly.
    `api_client`'s default `follow_redirects=True` silently follows that
    redirect, which is why this needs its own client with redirects
    disabled: a real, plain `curl http://host/dashboard` (as documented in
    README.md) does not follow redirects, and would see only a 307 rather
    than the dashboard's HTML. `@router.get("")` (empty string) is the
    fix -- this test pins that behavior down."""
    client = TestClient(create_app(settings=test_settings), follow_redirects=False)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_population_findings_route_returns_the_shell_html(api_client: TestClient) -> None:
    response = api_client.get("/dashboard/population-findings")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_reviews_route_returns_the_shell_html(api_client: TestClient) -> None:
    response = api_client.get("/dashboard/reviews")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_static_css_is_served_with_the_right_content_type(api_client: TestClient) -> None:
    response = api_client.get("/dashboard/static/dashboard.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_static_js_is_served_with_the_right_content_type(api_client: TestClient) -> None:
    response = api_client.get("/dashboard/static/dashboard.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_dashboard_js_uses_textcontent_not_innerhtml(api_client: TestClient) -> None:
    """A blanket-escaping regression guard for §4.3/§6's hard requirement:
    no rendered API value may ever be inserted via unsafe HTML
    concatenation. Checks for an actual assignment (the unsafe pattern),
    not the bare word, since this module's own docstring legitimately
    names the forbidden property when explaining why it's avoided."""
    response = api_client.get("/dashboard/static/dashboard.js")

    assert response.status_code == 200
    assert ".innerHTML =" not in response.text
    assert ".innerHTML +=" not in response.text


def test_dashboard_routes_do_not_require_a_live_database() -> None:
    # Mirrors tests/unit/api/test_app.py::test_create_app_wires_independent_instances:
    # a distinct, unreachable placeholder URL is enough to prove the
    # dashboard's routes work without ever touching Postgres, since
    # construction is lazy and the dashboard reads no repository/Engine at
    # all (docs/milestones/M10.md §1/§4.3). AUTH_ENABLED=False -- this test
    # constructs its own Settings directly rather than going through the
    # `test_settings` fixture (which already pins this), and is testing
    # DB-free construction, not authentication -- see docs/milestones/M13.md
    # §5.7.
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://unreachable-dashboard:5432/x", AUTH_ENABLED=False
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/dashboard")

    assert response.status_code == 200


def test_construction_failure_is_contained_and_does_not_prevent_the_app_from_starting(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Simulates exactly the packaging defect docs/milestones/M10.md
    # §4.3/§4.4/§8.6 names: a real, non-editable install missing the
    # dashboard's static assets directory. StaticFiles(check_dir=True,
    # its default) raises RuntimeError at construction time in that case
    # -- create_app() must contain that failure, not propagate it.
    monkeypatch.setattr(dashboard, "_STATIC_DIR", tmp_path / "does-not-exist")

    with patch("gov_platform.api.app.logger.exception") as mock_exception:
        app = create_app(settings=test_settings)

    mock_exception.assert_called_once()
    client = TestClient(app)

    # The rest of the application is completely unaffected -- /healthz
    # above all, the one endpoint this platform has always treated as an
    # unconditional liveness signal.
    assert client.get("/healthz").status_code == 200
    # The dashboard itself is simply absent, not present-but-broken: its
    # router was never registered, so FastAPI has no route to match here.
    assert client.get("/dashboard").status_code == 404
    assert client.get("/dashboard/static/dashboard.css").status_code == 404


def test_dashboard_static_assets_are_real_package_data_in_a_built_package(tmp_path: Path) -> None:
    """Verified directly against setuptools' own `build_py` command --
    the step that actually decides what ends up inside a real,
    non-editable install (mirroring `infra/docker/Dockerfile`'s
    `pip install .`) -- rather than merely assumed correct because
    editable/local development never exercises the failure mode
    (docs/milestones/M10.md §4.4). `build_py` (not `bdist_wheel`) is used
    deliberately: it needs no extra build dependency beyond the
    `setuptools` already required to build this project at all, and it is
    the exact command responsible for copying `package_data` into any
    build output, wheel or otherwise.
    """
    repo_root = Path(__file__).resolve().parents[3]
    build_dir = tmp_path / "build"
    egg_info_dir = repo_root / "src" / "gov_platform.egg-info"
    egg_info_pre_existed = egg_info_dir.exists()

    script = (
        "import sys; sys.argv = ['setup.py', 'build', '--build-lib', sys.argv[1]]; "
        "from setuptools import setup; setup()"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(build_dir)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        built_static_dir = build_dir / "gov_platform" / "api" / "dashboard_static"
        assert (built_static_dir / "index.html").is_file()
        assert (built_static_dir / "dashboard.css").is_file()
        assert (built_static_dir / "dashboard.js").is_file()
    finally:
        # `setup() ... build` writes src/gov_platform.egg-info as a side
        # effect (gitignored, but not something this test should leave
        # behind in a real working tree it doesn't own).
        if egg_info_dir.exists() and not egg_info_pre_existed:
            shutil.rmtree(egg_info_dir)
