"""`access.create_principal`'s CLI — mirrors `tests/integration/test_seed_registry_postgres.py`'s
pattern of calling `main(argv)` directly. Needs a real Postgres (it
persists real rows). CI-only (see `conftest.requires_postgres`).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from gov_platform.access.create_principal import main
from gov_platform.db.repositories.principal import PrincipalRepository
from gov_platform.schemas.principal import PrincipalRole
from tests.conftest import requires_postgres

pytestmark = requires_postgres


def test_main_creates_a_principal_and_prints_the_token_once(
    postgres_url: str, capsys: pytest.CaptureFixture[str], db_engine
) -> None:
    name = f"jane-{uuid4()}"
    exit_code = main(["--database-url", postgres_url, "--name", name, "--role", "REVIEWER"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"principal created: {name} (REVIEWER)" in output
    assert "token (shown once, not recoverable): " in output

    with Session(db_engine) as session:
        principals = PrincipalRepository().list(session)
    assert any(p.name == name and p.role is PrincipalRole.REVIEWER for p in principals)


def test_main_revokes_an_existing_principal(
    postgres_url: str, capsys: pytest.CaptureFixture[str], db_engine
) -> None:
    repository = PrincipalRepository()
    with Session(db_engine) as session:
        principal, _token = repository.create(
            session, name=f"jane-{uuid4()}", role=PrincipalRole.ADMIN
        )
        session.commit()

    exit_code = main(["--database-url", postgres_url, "--revoke", principal.id])

    assert exit_code == 0
    assert "principal revoked" in capsys.readouterr().out
    with Session(db_engine) as session:
        revoked = [p for p in repository.list(session) if p.id == principal.id]
    assert revoked[0].revoked_at is not None


def test_main_revoking_an_unknown_principal_returns_a_nonzero_exit_code(
    postgres_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--database-url", postgres_url, "--revoke", str(uuid4())])

    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_main_rejects_revoke_combined_with_name_and_role(postgres_url: str) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--database-url",
                postgres_url,
                "--revoke",
                str(uuid4()),
                "--name",
                "jane",
                "--role",
                "ADMIN",
            ]
        )


def test_main_rejects_neither_revoke_nor_name_and_role(postgres_url: str) -> None:
    with pytest.raises(SystemExit):
        main(["--database-url", postgres_url])
