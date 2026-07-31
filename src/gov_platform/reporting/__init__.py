"""Periodic, document-shaped compliance exports — architecture §14, M12.

This package holds `compliance_report.py` (the report's own Pydantic model
and bounded-window query functions) and `generate_report.py` (the
explicitly-invoked CLI). A new, small, top-level package because compliance
reporting spans data from `governance_engine`-adjacent tables and
`human_review`-adjacent tables alike, with no existing package that
naturally owns both — see `docs/milestones/M12.md` §5.1.
"""

from __future__ import annotations
