"""`api.admin._shared.resolve_reviewer` — pure, no DB, no HTTP. Covers
every branch directly rather than only indirectly through the two
routers that call it — see `docs/milestones/M13.md` §5.6.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from gov_platform.api.admin._shared import resolve_reviewer
from gov_platform.schemas.principal import Principal, PrincipalRole

_PRINCIPAL = Principal(
    id="principal-1", name="jane", role=PrincipalRole.REVIEWER, created_at=datetime.now(UTC)
)


def test_no_principal_and_no_reviewer_raises_422() -> None:
    with pytest.raises(HTTPException) as exc_info:
        resolve_reviewer(None, None)
    assert exc_info.value.status_code == 422


def test_no_principal_uses_the_request_bodys_reviewer() -> None:
    assert resolve_reviewer("someone", None) == "someone"


def test_a_principal_with_no_reviewer_supplied_uses_the_principals_name() -> None:
    assert resolve_reviewer(None, _PRINCIPAL) == "jane"


def test_a_principal_with_a_matching_reviewer_supplied_is_accepted() -> None:
    assert resolve_reviewer("jane", _PRINCIPAL) == "jane"


def test_a_principal_with_a_mismatched_reviewer_supplied_raises_422() -> None:
    with pytest.raises(HTTPException) as exc_info:
        resolve_reviewer("someone-else", _PRINCIPAL)
    assert exc_info.value.status_code == 422
