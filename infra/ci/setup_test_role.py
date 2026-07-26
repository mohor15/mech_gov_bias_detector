"""CI-only helper: enables login for the `gov_platform_app` role migration
0008 creates (without LOGIN/PASSWORD, deliberately — see that migration's
comments on keeping credentials out of version control) and sets its
password from an environment variable.

Not part of the application or its test suite — invoked as one CI step
between "apply migrations" and "run tests", using the admin connection to
grant the restricted role a real, connectable password for this ephemeral
CI database only. A real deployment's DBA runs the equivalent as an ops
step against a durable database, with a secret-managed password — this
script exists because CI's Postgres service container has neither.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql


def main() -> int:
    admin_url = os.environ["ADMIN_DATABASE_URL"]
    app_password = os.environ["GOV_PLATFORM_APP_PASSWORD"]

    # ALTER ROLE's PASSWORD clause is DDL: Postgres's grammar requires a
    # string literal there, not a bind parameter, so this can't use a
    # parameterized query the way a normal DML statement would. sql.Literal
    # still escapes/quotes the value safely — it's composed client-side into
    # the statement text, not sent as an untrusted parameter.
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            sql.SQL("ALTER ROLE gov_platform_app WITH LOGIN PASSWORD {}").format(
                sql.Literal(app_password)
            )
        )
        connection.commit()

    print("gov_platform_app role is now enabled for login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
