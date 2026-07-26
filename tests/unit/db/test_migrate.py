"""Tests the migration *runner mechanism* (discovery, ordering, idempotent
tracking) against a temp SQLite database with generic fixture SQL — not the
real Postgres-only content in infra/migrations/, which is applied and
verified in CI (see docs/milestones/M1.md). The runner itself is
dialect-agnostic; only the migration content targets Postgres specifically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect

from gov_platform.db.migrate import (
    _default_migrations_dir,
    _with_psycopg_driver,
    applied_migrations,
    apply_migrations,
    discover_migrations,
    main,
)


def _write_migration(directory: Path, filename: str, sql: str) -> None:
    (directory / filename).write_text(sql, encoding="utf-8")


def test_discover_migrations_sorts_by_filename(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0002_second.sql", "CREATE TABLE b (id INTEGER);")
    _write_migration(tmp_path, "0001_first.sql", "CREATE TABLE a (id INTEGER);")

    discovered = discover_migrations(tmp_path)

    assert [f.name for f in discovered] == ["0001_first.sql", "0002_second.sql"]


def test_apply_migrations_runs_pending_ones_in_order(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    _write_migration(tmp_path, "0002_create_bar.sql", "CREATE TABLE bar (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    applied = apply_migrations(engine, tmp_path)

    assert applied == ["0001_create_foo.sql", "0002_create_bar.sql"]
    tables = set(inspect(engine).get_table_names())
    assert {"foo", "bar"}.issubset(tables)


def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    first_run = apply_migrations(engine, tmp_path)
    second_run = apply_migrations(engine, tmp_path)

    assert first_run == ["0001_create_foo.sql"]
    assert second_run == []  # already applied — re-running must not re-execute or error


def test_apply_migrations_only_runs_newly_added_ones(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    apply_migrations(engine, tmp_path)

    _write_migration(tmp_path, "0002_create_bar.sql", "CREATE TABLE bar (id INTEGER PRIMARY KEY);")
    second_run = apply_migrations(engine, tmp_path)

    assert second_run == ["0002_create_bar.sql"]


def test_applied_migrations_reflects_tracking_table(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    apply_migrations(engine, tmp_path)

    assert applied_migrations(engine) == {"0001_create_foo.sql"}


def test_no_pending_migrations_returns_empty_list(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    assert apply_migrations(engine, tmp_path) == []


def test_default_migrations_dir_points_at_the_real_migrations_folder() -> None:
    resolved = _default_migrations_dir()

    assert resolved.name == "migrations"
    assert (resolved / "0001_create_systems.sql").exists()


def test_with_psycopg_driver_rewrites_bare_postgresql_scheme() -> None:
    assert _with_psycopg_driver("postgresql://u:p@host/db").startswith("postgresql+psycopg://")


def test_with_psycopg_driver_rewrites_bare_postgres_scheme() -> None:
    assert _with_psycopg_driver("postgres://u:p@host/db").startswith("postgresql+psycopg://")


def test_with_psycopg_driver_leaves_an_explicit_driver_untouched() -> None:
    url = "postgresql+psycopg://u:p@host/db"
    assert _with_psycopg_driver(url) == url


def test_main_applies_pending_migrations_and_reports_them(
    tmp_path: Path, capsys: Any
) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    database_url = f"sqlite:///{tmp_path / 'test.db'}"

    exit_code = main(["--database-url", database_url, "--migrations-dir", str(tmp_path)])

    assert exit_code == 0
    assert "Applied 1 migration(s): 0001_create_foo.sql" in capsys.readouterr().out


def test_main_reports_no_pending_migrations_on_a_second_run(
    tmp_path: Path, capsys: Any
) -> None:
    _write_migration(tmp_path, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    main(["--database-url", database_url, "--migrations-dir", str(tmp_path)])
    capsys.readouterr()

    exit_code = main(["--database-url", database_url, "--migrations-dir", str(tmp_path)])

    assert exit_code == 0
    assert "No pending migrations." in capsys.readouterr().out
