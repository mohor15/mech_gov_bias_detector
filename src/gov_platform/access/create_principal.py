"""CLI: provision (or revoke) a `Principal` — architecture (no numbered
section; see `docs/milestones/M13.md` Sourcing note), M13.

Mirrors `plugins/seed_registry.py`'s exact shape: `create_db_engine`
(the ordinary application connection is sufficient -- `principals` is an
ordinary admin-configuration table, not evidentiary, and migration
`0028` already grants `gov_platform_app` the privileges this needs), no
`bootstrap_plugins()` call (this tool touches no plugin registry),
explicit `--database-url`, no daemon.

Principals are provisioned this way, never through a self-service HTTP
endpoint, to sidestep the bootstrap problem every self-registration
design has: the very first administrator account has to be created by
*someone*, and an operator with database/filesystem access (the same
access every migration and every other CLI in this codebase already
requires) is this platform's own, already-established answer for every
other secret it has ever introduced (`SIGNING_PRIVATE_KEY`,
`FIELD_ENCRYPTION_KEY`) -- see `docs/milestones/M13.md` §4.4.

The plaintext token is printed to stdout exactly once, at creation time,
and never persisted or logged anywhere thereafter -- record it somewhere
durable (a secrets manager, not a commit).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from gov_platform.db.repositories.principal import PrincipalRepository
from gov_platform.db.session import create_db_engine
from gov_platform.schemas.principal import PrincipalRole


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision or revoke a Principal -- the only way to create one, "
        "there is no self-service HTTP registration endpoint (docs/milestones/M13.md §4.4)."
    )
    parser.add_argument("--database-url", required=True, help="The app's own runtime connection")
    parser.add_argument("--name", help="Required when creating a principal")
    parser.add_argument(
        "--role",
        choices=[role.value for role in PrincipalRole],
        help="Required when creating a principal",
    )
    parser.add_argument(
        "--revoke",
        metavar="PRINCIPAL_ID",
        help="Revoke an existing principal by id, instead of creating one",
    )
    args = parser.parse_args(argv)

    if args.revoke is not None and (args.name is not None or args.role is not None):
        parser.error("--revoke cannot be combined with --name/--role")
    if args.revoke is None and (args.name is None or args.role is None):
        parser.error("--name and --role are both required to create a principal")

    engine = create_db_engine(args.database_url)
    repository = PrincipalRepository()

    if args.revoke is not None:
        with Session(engine) as session:
            try:
                principal = repository.revoke(session, args.revoke)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            session.commit()
        print(f"principal revoked: {principal.name} ({principal.id})")
        return 0

    with Session(engine) as session:
        principal, token = repository.create(session, name=args.name, role=PrincipalRole(args.role))
        session.commit()

    print(f"principal created: {principal.name} ({principal.role.value})")
    print(f"token (shown once, not recoverable): {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
