"""Postgres persistence layer — architecture §16, formalized in M1.

`session.py` builds the one shared `Engine` the composition root injects
into both the Evidence Store and the Admin API. `models.py` holds the
SQLAlchemy declarative mappings used for querying; schema creation is owned
by `infra/migrations/*.sql` via `migrate.py`, not by these models. See
`repositories/` for the per-entity data-access classes.
"""
