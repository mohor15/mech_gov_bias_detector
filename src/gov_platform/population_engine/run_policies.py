"""CLI: evaluate every active `PopulationPolicyBinding` against its most
recently closed window and persist the results — architecture §13, M6.

This *is* "the async ingestion plane," per `docs/milestones/M6.md`
§4.1/§13.1: population-level policies cannot produce a synchronous,
per-event result (see `population_engine/__init__.py`), so evaluating
them happens on its own, explicitly-invoked cadence, entirely decoupled
from — and with zero latency effect on — either existing ingestion route.
Mirrors `plugins/seed_registry.py`'s and `audit/verify_chain.py`'s shape:
a separate, explicitly-invoked ops step, not something `create_app()`
does, and not a daemon or in-process scheduler (`docs/milestones/M6.md`
§13.4).

Windows are fixed, calendar-aligned, and closed in the past — by default,
"yesterday's full UTC day" — never `[now() - 30d, now())`. A rolling
window recomputed fresh on every invocation would have no stable identity
for the `UNIQUE (population_policy_id, system_id, window_start,
window_end)` constraint (migration `0015`) to make idempotent, and would
read right at its own boundary while ingestion is still writing. See
`docs/milestones/M6.md` §13.13. `--window-start`/`--window-end` exist to
override this explicitly (for a backfill, or a deliberate re-run of a
specific past window) — both or neither, never one alone.

Each binding is evaluated and persisted independently: one system's
binding failing (a transient DB error, a policy bug) is reported and
skipped, not allowed to abort every other system's run in the same
invocation — the batch-level analogue of the "no partial governance, but
also no single point of failure across independent systems" discipline.
Exits non-zero if any binding actually errored (excluding the clean,
expected "this window was already computed" skip) so an ops wrapper can
alert on real failures.

Every finding is signed the same way evidence records are
(`audit/signing.py`, unchanged) and run through `run_sandboxed`
(`plugins/sandbox.py`) — the same timeout/exception isolation every other
plugin call in this codebase gets; the original design draft omitted this
and it was added as an implementation-readiness requirement during the
hostile-review pass (`docs/milestones/M6.md` §4.5).

M8 (architecture §10): each binding's own admin-configured `parameters`
are attached onto its window immediately before `evaluate()` is called,
not threaded through `build_population_window` itself, which stays
generic and binding-unaware — see `docs/milestones/M8.md` §4.3/§13.2.

M9 (architecture §12): immediately after a `FLAGGED` finding's own
transaction commits, a `PopulationFindingReview` is created in a
**separate** transaction — the identical "decoupled, idempotent,
never-fails-the-more-important-write" pattern
`audit/evidence_store.py`'s `_queue_verdict_review` uses for `Verdict`,
applied here for consistency even though this batch job's existing
per-binding failure isolation already made the original (rejected)
same-transaction coupling comparatively low-risk — a review-row failure
here just means this window's finding isn't committed this run and gets
cleanly recomputed on the next invocation, never a caller-facing failure
with no retry contract the way a live ingestion request would have. See
`docs/milestones/M9.md` §3.4.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gov_platform.audit.signing import EvidenceSigner, load_signer
from gov_platform.audit.verify_population_findings import population_finding_hash
from gov_platform.config.settings import get_settings
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.population_finding import PopulationFindingRepository
from gov_platform.db.repositories.population_finding_review import (
    PopulationFindingReviewRepository,
)
from gov_platform.db.repositories.population_policy_binding import (
    PopulationPolicyBindingRepository,
)
from gov_platform.db.session import create_db_engine
from gov_platform.plugins import registry
from gov_platform.plugins.bootstrap import bootstrap_plugins
from gov_platform.plugins.sandbox import run_sandboxed
from gov_platform.population_engine.window import build_population_window
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType
from gov_platform.schemas.population_finding import PopulationFindingOutcome
from gov_platform.schemas.population_policy_binding import PopulationPolicyBinding

logger = logging.getLogger(__name__)


def default_window(as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """Yesterday's full UTC day, relative to `as_of` (defaults to
    `datetime.now(UTC)`) — fixed, calendar-aligned, closed in the past.
    `as_of` is a seam for tests, not a CLI argument: real invocations
    always mean "as of right now"."""
    now = as_of or datetime.now(UTC)
    today_midnight_utc = datetime(now.year, now.month, now.day, tzinfo=UTC)
    window_end = today_midnight_utc
    window_start = window_end - timedelta(days=1)
    return window_start, window_end


def run_population_policy_binding(
    engine: Engine,
    binding: PopulationPolicyBinding,
    *,
    window_start: datetime,
    window_end: datetime,
    plugin_registration_repository: PluginRegistrationRepository,
    population_finding_repository: PopulationFindingRepository,
    population_finding_review_repository: PopulationFindingReviewRepository,
    signer: EvidenceSigner,
) -> str:
    """Evaluate one binding for `[window_start, window_end)`. Returns a
    short, human-readable status line -- never raises for an expected
    "already computed" duplicate (translated to a clean SKIP line, per
    the `UNIQUE` constraint's whole purpose, see `docs/milestones/M6.md`
    §13.13); any other exception propagates to the caller, which reports
    it as a real error and moves on to the next binding."""
    with Session(engine) as session:
        registrations = plugin_registration_repository.list_by_type_and_plugin_id(
            session,
            plugin_type=PluginType.POPULATION_POLICY,
            plugin_id=binding.population_policy_id,
        )
    production_registration = next(
        (r for r in registrations if r.lifecycle_state is PluginLifecycleState.PRODUCTION),
        None,
    )
    if production_registration is None:
        return (
            f"SKIP {binding.system_id} -> {binding.population_policy_id}: "
            "no PRODUCTION population policy registered"
        )

    population_policy_cls = registry.get_population_policy_class(
        production_registration.plugin_id, production_registration.version
    )
    if population_policy_cls is None:
        return (
            f"SKIP {binding.system_id} -> {binding.population_policy_id}: PRODUCTION "
            f"registration exists but version {production_registration.version} is not "
            "deployed in this process"
        )

    window = build_population_window(
        engine, system_id=binding.system_id, window_start=window_start, window_end=window_end
    )
    # M8: attach this binding's own admin-configured parameters onto the
    # window immediately before evaluating -- build_population_window
    # itself stays generic and binding-unaware (docs/milestones/M8.md
    # §4.3/§13.2).
    window = window.model_copy(update={"parameters": binding.parameters})
    population_policy = population_policy_cls()
    finding = run_sandboxed(lambda: population_policy.evaluate(window))

    signature = signer.sign(population_finding_hash(finding))

    with Session(engine) as session:
        try:
            record = population_finding_repository.create(
                session, finding, signature=signature, signing_key_id=signer.key_id
            )
            session.commit()
        except ValueError:
            return (
                f"SKIP {binding.system_id} -> {binding.population_policy_id}: window "
                f"[{window_start.isoformat()}, {window_end.isoformat()}) already computed"
            )

    # M9: a separate transaction, deliberately not the one above -- see
    # this module's docstring and `_queue_population_finding_review`'s own.
    _queue_population_finding_review(
        engine, record.id, record.outcome, population_finding_review_repository
    )

    return (
        f"FINDING {binding.system_id} -> {binding.population_policy_id}: "
        f"{record.outcome.value} [{window_start.date()}, {window_end.date()})"
    )


def _queue_population_finding_review(
    engine: Engine,
    population_finding_id: str,
    outcome: PopulationFindingOutcome,
    population_finding_review_repository: PopulationFindingReviewRepository,
) -> None:
    """Creates a `PopulationFindingReview` for `population_finding_id`, if
    `outcome` qualifies, in a brand-new `Session` — never the one the
    finding's own commit just used. Any failure here is logged and
    swallowed, never propagated to the caller: mirrors
    `audit/evidence_store.py`'s `_queue_verdict_review` exactly, applied
    here for consistency (`docs/milestones/M9.md` §3.4)."""
    if outcome is not PopulationFindingOutcome.FLAGGED:
        return
    try:
        with Session(engine) as review_session:
            population_finding_review_repository.create(review_session, population_finding_id)
            review_session.commit()
    except Exception:
        logger.exception(
            "population_finding_review_creation_failed",
            extra={"extra_fields": {"population_finding_id": population_finding_id}},
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate every active PopulationPolicyBinding against its most recently "
        "closed window and persist the results."
    )
    parser.add_argument("--database-url", required=True, help="The app's own runtime connection")
    parser.add_argument("--window-start", required=False, help="ISO 8601 UTC timestamp, inclusive.")
    parser.add_argument("--window-end", required=False, help="ISO 8601 UTC timestamp, exclusive.")
    args = parser.parse_args(argv)

    if bool(args.window_start) != bool(args.window_end):
        parser.error("--window-start and --window-end must be given together, or not at all")

    if args.window_start and args.window_end:
        window_start = datetime.fromisoformat(args.window_start)
        window_end = datetime.fromisoformat(args.window_end)
    else:
        window_start, window_end = default_window()

    bootstrap_plugins()
    engine = create_db_engine(args.database_url)
    settings = get_settings()
    signer = load_signer(settings.SIGNING_PRIVATE_KEY, key_id=settings.SIGNING_KEY_ID)

    plugin_registration_repository = PluginRegistrationRepository()
    population_policy_binding_repository = PopulationPolicyBindingRepository()
    population_finding_repository = PopulationFindingRepository()
    population_finding_review_repository = PopulationFindingReviewRepository()

    with Session(engine) as session:
        bindings = population_policy_binding_repository.list_active(session)

    had_error = False
    for binding in bindings:
        try:
            print(
                run_population_policy_binding(
                    engine,
                    binding,
                    window_start=window_start,
                    window_end=window_end,
                    plugin_registration_repository=plugin_registration_repository,
                    population_finding_repository=population_finding_repository,
                    population_finding_review_repository=population_finding_review_repository,
                    signer=signer,
                )
            )
        except Exception as exc:
            had_error = True
            print(f"ERROR {binding.system_id} -> {binding.population_policy_id}: {exc}")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
