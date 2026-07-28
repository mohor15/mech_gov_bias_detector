"""The "Event Lake" read path — architecture §6/§13, M6.

No new physical store: `decision_events` (migration `0003`) already holds
`protected_attribute_refs`/`decision_output`/`occurred_at` for every
event ever ingested, joined to `model_versions`/`systems` for identity.
"Event Lake" names this module's new *batch, windowed read pattern* over
that existing table — see `docs/milestones/M6.md` §4.2/§13.2.

Resolves DIRECT-ness against the DB-backed `protected_attribute_rules`
(M5), not `protected_attributes/classification.py`'s static copy — see
`docs/milestones/M6.md` §13.15. Attribute *values* come from
`decision_events.protected_attribute_refs` directly, not from
`protected_attribute_resolutions`, which only ever holds classification,
never the value itself (the correctness bug found during the
hostile-review pass — see §4.2's correction).

Scoped to exactly one favorable-outcome key, `decision_output["approved"]`
— both first-party adapters (`SyntheticAdapter`, `CreditScorecardAdapter`)
use it, and this milestone's one policy (adverse impact ratio) is itself
scoped to `FINANCE`, the only domain with a real adapter. A general,
per-domain-configurable outcome key is exactly the kind of "no second case
yet" generalization this project has consistently declined — see
`docs/milestones/M6.md` §13.9.

Runs under `REPEATABLE READ` (§13.13, reversed from this milestone's first
design draft): this issues more than one query (the domain lookup, the
ruleset lookup, one aggregate per `DIRECT` attribute), and under plain
read-committed nothing would guarantee they see the same snapshot — an
event or rule committed between them could appear in one read and not
another, silently corrupting a count.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.population_engine.base import PopulationGroupCount, PopulationWindow
from gov_platform.schemas.protected_attribute_rule import ProtectedAttributeRuleClassification

# Cast to jsonb inline rather than migrating protected_attribute_refs/
# decision_output to a native json/jsonb column type -- both are stored as
# plain TEXT (see infra/migrations/0003_create_decision_events.sql), and
# changing that would be an unrequested schema change to an existing
# table, something no M6 decision calls for (see docs/milestones/M6.md
# §5's "no changes to any existing table").
_GROUP_COUNTS_SQL = text(
    """
    SELECT
        de.protected_attribute_refs::jsonb ->> :attr_name AS attribute_value,
        COUNT(*) AS total_count,
        COUNT(*) FILTER (
            WHERE de.decision_output::jsonb ->> 'approved' = 'true'
        ) AS favorable_outcome_count
    FROM decision_events de
    JOIN model_versions mv ON mv.id = de.model_version_id
    WHERE mv.system_id = :system_id
      AND de.occurred_at >= :window_start
      AND de.occurred_at < :window_end
      AND (de.protected_attribute_refs::jsonb ->> :attr_name) IS NOT NULL
    GROUP BY attribute_value
    ORDER BY attribute_value
    """
)


def build_population_window(
    engine: Engine, *, system_id: str, window_start: datetime, window_end: datetime
) -> PopulationWindow:
    """Builds one `PopulationWindow` for `system_id` over `[window_start,
    window_end)`. Raises `ValueError` if `system_id` doesn't exist (a
    `PopulationPolicyBinding`'s own foreign key already guarantees this in
    the real batch-runner path -- see `db/repositories/population_policy_binding.py`
    -- but this function is also unit-testable standalone). A system with
    no registered domain, or a domain with no `DIRECT` rules, produces an
    empty window (`group_counts=[]`) -- a legitimate, non-error case, the
    same "nothing to resolve" treatment `ProtectedAttributeResolver` gives
    an unrecognized domain.
    """
    with Session(engine) as session:
        # Must be set before the first query -- SQLAlchemy opens the
        # underlying transaction lazily, on first use, at whatever
        # isolation level is configured at that point.
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        system = SystemRepository().get(session, system_id)
        if system is None:
            raise ValueError(f"no system with id {system_id!r}")

        # A system with no registered domain has nothing to resolve -- the
        # same "nothing to resolve, not an error" treatment
        # ProtectedAttributeResolver._rules_for_domain gives None (see
        # protected_attributes/resolver.py); the DB-backed repository's
        # own rules_for_domain is typed for a known, non-None domain.
        rules = (
            ProtectedAttributeRuleRepository().rules_for_domain(session, system.domain)
            if system.domain is not None
            else None
        )
        direct_attributes = sorted(rules.direct_attributes) if rules is not None else []
        classification_snapshot = {
            attribute_name: ProtectedAttributeRuleClassification.DIRECT.value
            for attribute_name in direct_attributes
        }

        group_counts: list[PopulationGroupCount] = []
        for attribute_name in direct_attributes:
            rows = session.execute(
                _GROUP_COUNTS_SQL,
                {
                    "attr_name": attribute_name,
                    "system_id": system_id,
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
            group_counts.extend(
                PopulationGroupCount(
                    attribute_name=attribute_name,
                    attribute_value=attribute_value,
                    total_count=total_count,
                    favorable_outcome_count=favorable_outcome_count,
                )
                for attribute_value, total_count, favorable_outcome_count in rows
            )

    return PopulationWindow(
        system_id=system_id,
        window_start=window_start,
        window_end=window_end,
        group_counts=group_counts,
        classification_snapshot=classification_snapshot,
    )
