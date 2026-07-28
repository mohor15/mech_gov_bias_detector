"""`observability.metrics.disagreement_rate` — the one piece of M7's
metrics shaping that's pure and DB-free. Every other function in this
module is a real aggregate query, covered instead in
`tests/integration/test_metrics_postgres.py` — see
`docs/milestones/M7.md` §10.
"""

from __future__ import annotations

from gov_platform.observability.metrics import disagreement_rate


def test_returns_none_when_there_is_nothing_comparable() -> None:
    """Zero comparable pairs -- not a 0.0 rate, not a division by zero."""
    assert disagreement_rate(comparable_count=0, disagreement_count=0) is None


def test_computes_the_rate_when_some_pairs_disagree() -> None:
    assert disagreement_rate(comparable_count=4, disagreement_count=1) == 0.25


def test_zero_disagreements_is_a_real_zero_not_none() -> None:
    assert disagreement_rate(comparable_count=10, disagreement_count=0) == 0.0


def test_full_disagreement_is_one() -> None:
    assert disagreement_rate(comparable_count=3, disagreement_count=3) == 1.0
