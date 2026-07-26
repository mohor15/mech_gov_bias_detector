"""Minimal migration runner.

Applies numbered `.sql` files from a directory in filename order, tracking
what's already been applied in a `schema_migrations` table so re-running is
a no-op. No Alembic: the frozen implementation plan calls for plain numbered
`.sql` files, and a runner this small doesn't justify a new dependency.

The runner mechanism itself (discovery, ordering, idempotent tracking) is
dialect-agnostic and is unit-tested locally against SQLite with generic
fixture SQL — see `tests/unit/db/test_migrate.py`. The real migration
content in `infra/migrations/` targets Postgres only (per the approved M1
strategy) and is applied and verified in CI, not locally.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL
)
"""


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """All `.sql` files in `migrations_dir`, sorted by filename."""
    return sorted(migrations_dir.glob("*.sql"))


def applied_migrations(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        connection.execute(text(_TRACKING_TABLE_DDL))
        rows = connection.execute(text("SELECT filename FROM schema_migrations"))
        return {row[0] for row in rows}


def apply_migrations(engine: Engine, migrations_dir: Path) -> list[str]:
    """Apply every pending migration in order. Returns the filenames applied
    this run (empty if everything was already applied)."""
    already_applied = applied_migrations(engine)
    newly_applied: list[str] = []

    for migration_file in discover_migrations(migrations_dir):
        if migration_file.name in already_applied:
            continue

        sql = migration_file.read_text(encoding="utf-8")
        record_migration = text(
            "INSERT INTO schema_migrations (filename, applied_at) "
            "VALUES (:filename, CURRENT_TIMESTAMP)"
        )
        with engine.begin() as connection:
            connection.execute(text(sql))
            connection.execute(record_migration, {"filename": migration_file.name})
        newly_applied.append(migration_file.name)

    return newly_applied


def _default_migrations_dir() -> Path:
    # src/gov_platform/db/migrate.py -> repo root -> infra/migrations
    return Path(__file__).resolve().parents[3] / "infra" / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending SQL migrations.")
    parser.add_argument("--database-url", required=True, help="Admin-privileged connection string")
    parser.add_argument("--migrations-dir", type=Path, default=_default_migrations_dir())
    args = parser.parse_args(argv)

    engine = create_engine(args.database_url)
    applied = apply_migrations(engine, args.migrations_dir)

    if applied:
        print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("No pending migrations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
