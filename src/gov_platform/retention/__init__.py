"""Retention tiers for the two non-evidentiary, privilege-unlocked tables
this schema has — architecture §13, M11. See
`retention/purge_expired_records.py` and `docs/milestones/M11.md` §5.2 for
the full design rationale.
"""

from __future__ import annotations
