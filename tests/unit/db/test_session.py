"""`db.session.create_db_engine`/`with_psycopg_driver` — pure URL/engine
construction, no live database needed (`create_engine` is lazy).

Regression coverage for a real CI-found bug (see `docs/milestones/M11.md`'s
own production-readiness review): a bare `postgresql://`/`postgres://` URL
passed to `create_db_engine` (e.g. `ADMIN_DATABASE_URL`, which is
deliberately bare-scheme because it's also handed directly to
`psycopg.connect()` by `infra/ci/setup_test_role.py`) previously reached
`sqlalchemy.create_engine` unnormalized, defaulting to the `psycopg2`
dialect -- not a dependency of this project -- and failing with
`ModuleNotFoundError` the moment a connection was attempted.
`db/migrate.py` already solved this for its own `--database-url` argument
at M1; `with_psycopg_driver` moved here at M11 so `create_db_engine`'s
other callers get the identical protection.
"""

from __future__ import annotations

from gov_platform.db.session import create_db_engine, with_psycopg_driver


def test_with_psycopg_driver_rewrites_bare_postgresql_scheme() -> None:
    assert with_psycopg_driver("postgresql://u:p@host/db").startswith("postgresql+psycopg://")


def test_with_psycopg_driver_rewrites_bare_postgres_scheme() -> None:
    assert with_psycopg_driver("postgres://u:p@host/db").startswith("postgresql+psycopg://")


def test_with_psycopg_driver_leaves_an_explicit_driver_untouched() -> None:
    url = "postgresql+psycopg://u:p@host/db"
    assert with_psycopg_driver(url) == url


def test_create_db_engine_normalizes_a_bare_admin_style_url() -> None:
    # The exact shape ADMIN_DATABASE_URL has in CI/infra/ci/setup_test_role.py.
    engine = create_db_engine("postgresql://postgres:postgres@localhost:5432/gov_platform")

    assert engine.url.drivername == "postgresql+psycopg"


def test_create_db_engine_leaves_an_already_qualified_url_untouched() -> None:
    # The exact shape POSTGRES_URL/GOV_PLATFORM_DATABASE_URL already have.
    engine = create_db_engine(
        "postgresql+psycopg://gov_platform_app:pw@localhost:5432/gov_platform"
    )

    assert engine.url.drivername == "postgresql+psycopg"
