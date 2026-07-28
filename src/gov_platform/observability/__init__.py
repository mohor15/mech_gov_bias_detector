"""Cross-cutting observability primitives.

M0: structured logging (`logging.py`). M7 adds `metrics.py` — system- and
governance-health metrics, architecture §9 — as a sibling module in this
same package, not a separate ``monitoring`` package as originally
anticipated here: a JSON-query-backed metrics module and a JSON-line
logging formatter are the same kind of cross-cutting, non-domain concern,
and splitting them into two packages for that reason alone would be an
organizing principle with no real second case behind it (see
`docs/milestones/M7.md` §13.1/§13.8 for the identical "no abstraction for
one case" reasoning applied to this milestone's other structural
choices). No dashboard/UI lives here either — see `metrics.py`'s own
docstring and `docs/milestones/M7.md` §13.2.
"""
