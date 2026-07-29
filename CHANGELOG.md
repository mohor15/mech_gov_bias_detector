# Changelog

All notable changes to this project are documented in this file. Entries are
grouped by milestone (`ARCH-GOV-002` / `IMPL-GOV-001`), not by release date,
since this project ships as a sequence of frozen, incremental milestones
rather than continuous releases.

## [0.11.0-m10] — 2026-07-29 — M10: Compliance Dashboard

Delivers architecture §11 ("Compliance Dashboard"): a small set of
read-only HTML views rendering data M6/M7/M9 already compute and already
expose via JSON — system/governance health, population findings, and the
Human Review Workflow queue. Static HTML/CSS/vanilla JavaScript, served
from the existing FastAPI app, fetching the same JSON endpoints every
other client already uses. **Zero new endpoints, zero new database
tables, zero new external dependencies.** The first milestone whose
entire job is presentation, not computation, and the first UI this
platform has ever built. Full design rationale, this milestone's own
hostile-review record (three findings severe enough to reverse the
original design, two folded in as amendments, two new ambiguities
discovered), and the post-implementation production-readiness review:
[`docs/milestones/M10.md`](docs/milestones/M10.md).

### Added
- `api/dashboard.py` — a plain `APIRouter` registered with `prefix="/dashboard"`, serving the identical static shell HTML at `GET /dashboard`, `GET /dashboard/population-findings`, and `GET /dashboard/reviews`; the client-side JavaScript, not this router, decides what to render based on the current path. `register_dashboard(app)` mounts the static assets and includes the router in one call, designed to be invoked inside a `try`/`except` (see Fixed below).
- `api/dashboard_static/index.html`, `dashboard.css`, `dashboard.js` — the dashboard's entire client: three views (Overview, Population Findings, Review Queue), each populated by plain `fetch()` calls against `GET /v1/admin/metrics`, `GET /readyz`, `GET /v1/admin/population-findings`, `GET /v1/admin/systems`, `GET /v1/admin/verdict-reviews`, and `GET /v1/admin/population-finding-reviews` — no new endpoint, no changed response shape. Every rendered value is inserted via `textContent`, never `innerHTML` concatenation, with no field-specific exception list. Every view renders a visible, honest error state on a failed or non-2xx `fetch()`, never a silent blank page.
- `[tool.setuptools.package-data]` in `pyproject.toml` — declares `dashboard_static/*.html`/`*.css`/`*.js` as real package data, verified directly (via `setuptools`' own `build_py` command, not merely assumed) to be included in a real, non-editable install — the exact path `infra/docker/Dockerfile`'s `pip install .` and CI's `docker-smoke` job exercise.
- `tests/unit/api/test_dashboard.py` — route/content-type coverage, a regression guard against `innerHTML` assignment, a direct proof the dashboard needs no live database at construction time, a simulated packaging-failure test proving containment (`/healthz` still works, the dashboard routes 404, no exception propagates), and an automated re-run of the `build_py` packaging verification above.

### Changed
- `api/app.py` — `register_dashboard(app)` is called inside its own `try`/`except Exception`, logging loudly on failure — the one router registration in this composition root that isn't a bare, unguarded call, and deliberately so (see Fixed below).

### Fixed
- **Implementation-time**: `GET /dashboard` 307-redirected to `/dashboard/` instead of returning `200` directly. Literally following §8.7's own recommended pattern (`prefix="/dashboard"` plus a relative `@router.get("/")` decorator for the index route) registers the exact path `/dashboard/`, not `/dashboard` — a bare request to the latter needs Starlette's default slash-redirect to reach it. Silently broke README's own documented `curl http://127.0.0.1:8000/dashboard` example (no `-L`, so it would print nothing) and wasn't caught by the initial test suite because `TestClient`'s default `follow_redirects=True` transparently follows the extra hop. Found by exercising the real app with `uvicorn` and `curl` directly, not just the test suite. Fixed: `@router.get("/")` → `@router.get("")` for the index route only; pinned down by a new regression test (`test_overview_route_matches_exactly_without_a_redirect`) using a `follow_redirects=False` client. See `docs/milestones/M10.md` §10 for the full report.

_(the remainder found and corrected during this milestone's own hostile-review pass, before implementation began — see `docs/milestones/M10.md`'s "Revision note" for the full record)_
- The first design draft described a dashboard packaging mistake as "the dashboard... silently 404s." Verified directly against Starlette's own source: `StaticFiles(check_dir=True)` (its default) raises `RuntimeError` at *construction* time, inside `create_app()` itself, if its directory is missing — exactly what a real, non-editable install missing `package_data` produces. Left unguarded, that would have prevented `create_app()` from ever returning an application object at all, taking `/healthz` down with it. Fixed before implementation: the dashboard's `StaticFiles` mount and router registration are constructed inside their own `try`/`except` in `create_app()`, mirroring the "a failure in this non-essential subsystem must never take down what matters more" precedent M9 already established for `_queue_verdict_review`.
- The first design draft proposed a brand-new top-level package (`gov_platform/dashboard/static/`) for the static assets while putting the router itself in the existing `api/` package — inconsistent with this project's own "a new top-level package only when nothing existing is a natural home" precedent (M9's `human_review/`). Fixed before implementation: static assets moved to `api/dashboard_static/`, alongside the router that serves them.
- The first design draft named exactly three fields (`rationale`, `resolution_notes`, `reviewer`) as requiring safe DOM insertion. Found to be actively misleading, not merely incomplete: `System.name` is a concrete counter-example the list missed entirely — no character/length restriction beyond `min_length=1`, auto-provisioned directly from the *public*, unauthenticated ingestion endpoint's `system_id`/`source_system` fields. Fixed before implementation: the guidance is now a blanket rule — every string value from any API response is inserted via `textContent`, unconditionally, no exception list.
- Client-side fetch-failure handling was entirely absent from the first design draft. Fixed before implementation: every view now renders a visible, honest error state on a failed or non-2xx `fetch()` — most important exactly when the underlying database is unhealthy, the same moment the Overview page's own data is least likely to be available.

### Deferred
No new migration, no new table, no new JSON endpoint. Interactive claim/release/resolve actions from the dashboard itself (read-only for this milestone, `docs/milestones/M10.md` §8.1); a combined "dashboard summary" endpoint (considered and declined — three to four `fetch()` calls is not a real performance problem today); pagination on the endpoints the dashboard depends on (a real, pre-existing gap, confirmed out of M10's own additive scope, its real-scale consequence — a browser-tab freeze, not a mild inconvenience — named more plainly than the first draft did); real-time push/auto-refresh; periodic report generation/export (M12); encryption at rest and retention (M11); a general "list all Verdicts"/"list all Findings" view (M9's own declined scope); accessibility/mobile-responsiveness auditing; browser-automation test coverage (Selenium/Playwright, declined); authentication anywhere in this platform (still M13, now an eighth-consecutive-milestone gap); multi-tenancy/multi-plane deployment/mTLS (M13).

## [0.10.0-m9] — 2026-07-29 — M9: Human Review Workflow

Delivers architecture §12 ("Human Review Workflow"): the queue that
finally gives an `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` `GovernanceVerdict`
(M5) and a `FLAGGED` `PopulationFinding` from either population policy
(M6/M8) somewhere to go — the one deferred item named explicitly in every
design document since M5, never touched until now. Two new tables
(`verdict_reviews`, `population_finding_reviews`), each a reopenable
`OPEN → IN_REVIEW → RESOLVED` workflow record with a real, partial-
unique-index-backed foreign key to exactly one already-persisted
`Verdict`/`PopulationFinding`. Full design rationale, this milestone's own
two-pass hostile-review record (eleven findings from the first pass, three
of them severe enough to reverse the original design; the three remaining
open questions approved and the design frozen before implementation
began), and the post-implementation production-readiness review:
[`docs/milestones/M9.md`](docs/milestones/M9.md).

### Added
- `schemas/human_review.py` — `VerdictReviewStatus`/`VerdictReviewResolution`/`VerdictReview`, `PopulationFindingReviewStatus`/`PopulationFindingReviewResolution`/`PopulationFindingReview` (two separate enum pairs, not one shared pair — mirroring `PolicyBindingLifecycleState`/`PopulationPolicyBindingLifecycleState`'s own precedent for exactly this duplication), and `_REVIEWABLE_VERDICT_STATUSES` — the one canonical `{ESCALATE_FOR_REVIEW, RECOMMEND_HOLD}` definition both the live write path and the reconciliation tool import.
- `db/repositories/verdict_review.py`, `db/repositories/population_finding_review.py` — `VerdictReviewRepository`/`PopulationFindingReviewRepository`: an idempotent-upsert `create` (`INSERT ... ON CONFLICT (verdict_id) WHERE status != 'RESOLVED' DO NOTHING`), and `claim`/`release`/`resolve` as single conditional `UPDATE ... WHERE id = :id AND status = '<expected>'` statements (checked by row count, not a read-then-write two-step) — a materially stronger concurrency-safety pattern than this codebase's own `set_lifecycle_state` precedent uses elsewhere (see Confirmed-not-fixed below). `resolve` requires `reviewer` to match who claimed the item.
- `VerdictRepository.get_many` — batch-fetches multiple `Verdict`s (two queries total, not two per id) for the verdict-reviews list endpoint's embedded data, avoiding an N+1 query pattern the original design's implementation plan didn't call out.
- `api/admin/verdict_reviews.py`, `api/admin/population_finding_reviews.py` — five endpoints each (`list`/`get`/`claim`/`release`/`resolve`), embedding the full `Verdict`/`PopulationFinding` in every response. `claim`/`release`/`resolve` translate a repository-raised `ValueError` into a `409` via an explicit `try`/`except`, not by letting it fall through to `api/app.py`'s global handler (which defaults to `422`). The verdict-reviews list endpoint supports an additional `severity` filter (joins to the referenced `Verdict`'s own `status`) and both list endpoints default to oldest-open-first ordering.
- `human_review/backfill_reviews.py` — the reconciliation tool: creates an `OPEN` review for every reviewable `Verdict`/`PopulationFinding` with no active review yet. Idempotent via the same upsert semantics as the live path; safe to run once at rollout and safe to re-run periodically thereafter (an ops cron entry, or manually after any incident), including concurrently with live traffic.
- Migrations `0023`–`0024` — `verdict_reviews`, `population_finding_reviews`: both purely additive `CREATE TABLE`, each with an explicit `ON DELETE RESTRICT` foreign key, a partial unique index (`one_open_..._per_...`, scoped to non-`RESOLVED` rows — not a plain `UNIQUE`, which would have permanently foreclosed reopening a resolved review) and a `status` index for the list endpoints' primary query.

### Changed
- `audit/evidence_store.py` — `EvidenceStore.append` gains `_queue_verdict_review`, called immediately after `append`'s own transaction commits, in a **separate** `Session`: creates a `VerdictReview` for a qualifying `Verdict`, catching and logging (never re-raising) any failure of its own. `append`'s own transaction body — the same five-to-six-table write every milestone since M2 has added to — is otherwise byte-for-byte unchanged.
- `population_engine/run_policies.py` — `run_population_policy_binding` gains the identical decoupled, idempotent, failure-swallowing review-row creation for `PopulationFindingReview`, applied for consistency even though this batch job's existing per-binding retry tolerance already made the (rejected) same-transaction alternative comparatively low-risk here.
- `api/dependencies.py`, `api/app.py` — three new repositories (`VerdictRepository`, `VerdictReviewRepository`, `PopulationFindingReviewRepository`) and two new Admin API routers wired into the composition root, the same pattern every prior milestone's new surfaces followed.

### Fixed
_(found and corrected during this milestone's own two-pass hostile review, before implementation began — see `docs/milestones/M9.md`'s "Design Review" section for the full record)_
- The first design draft recommended creating a `VerdictReview` **inside** `EvidenceStore.append`'s own transaction. A bug in this new, non-essential workflow code would have rolled back the hash-chained evidence record for a real, already-made governance decision — this platform's single most important guarantee, put at risk by a feature that has nothing to do with evidence integrity. Fixed before implementation: review-row creation moved to a separate transaction, called only after the evidence write's own commit succeeds, with its own failure logged and swallowed rather than propagated. The identical fix was applied to `run_policies.py`'s `PopulationFindingReview` creation for consistency.
- The first design draft specified a full `UNIQUE (verdict_id)` constraint, reproducing — in a brand-new table — the exact defect migration `0022` (M8) already fixed once for `population_policy_bindings`: a plain uniqueness constraint that permanently forecloses a legitimate future need (reopening a previously-resolved review) the moment one appears. Fixed before implementation: a partial unique index scoped to non-`RESOLVED` rows, mirroring M8's own fix exactly.
- The first design draft's workflow was a strictly linear three-state machine (`OPEN → IN_REVIEW → RESOLVED`) with no way back from `IN_REVIEW`. An abandoned claim (a reviewer reassigned, on leave, or who simply forgot) would have been **permanently** hidden from anyone filtering the queue by `status=OPEN` — worse than the item never having been claimed at all, given this platform has no authentication to even identify who claimed it for follow-up. Fixed before implementation: an explicit `IN_REVIEW → OPEN` release transition.
- Decoupling review-row creation from the write it depends on (the first fix above) reopens a narrow race between the live write path and the reconciliation tool, found during the *second* hostile-review pass specifically: both can attempt to insert a review row for the same verdict/finding, and a plain `INSERT` would let whichever writer loses that race fail outright — in the worse direction, a live ingestion request racing an ops-triggered reconciliation run. Fixed: both writers use `INSERT ... ON CONFLICT ... DO NOTHING`, and the reconciliation tool itself is reframed from a one-time migration helper into a standing tool safe to re-run periodically, specifically to serve as this ongoing safety net.
- Confirmed, not fixed — a genuinely pre-existing defect found as a byproduct of this milestone's own foreign-key design: `verdicts`/`findings`/`decision_events`/`model_versions`/`systems`/`verdict_findings` lack the `REVOKE UPDATE, DELETE` database-privilege lockdown `evidence_chain`/`population_findings` have, true since M1/M5 and never named in any design document until M9 added the first real foreign key pointing at `verdicts`. Documented as a candidate for a dedicated, separate follow-up.
- Confirmed, not fixed — a second genuinely pre-existing defect, found as a byproduct of designing this milestone's own claim/resolve concurrency pattern: `PopulationPolicyBindingRepository.set_lifecycle_state` (and `PolicyBindingRepository`'s identical twin) use a read-then-write pattern with no conditional-update protection against a concurrent lifecycle transition. Documented as a candidate for a dedicated, separate follow-up.

### Deferred
Two purely additive migrations, no existing table's schema or meaning altered. A UI/dashboard for this workflow (M10's Compliance Dashboard); a notification/paging mechanism for newly `OPEN` items (pull-only, mitigated only by the oldest-open-first default ordering); authentication on the ten new endpoints, or anywhere else (still `M13`, now a sixth-consecutive-milestone gap, sharpened here more than at any prior point — the first milestone where an unauthenticated caller can fabricate a specific, named person's professional judgment about a real bias finding); reviewer identity/roles/RBAC; signing or chaining a review's resolution into the tamper-evident audit trail (a genuine, undecided-by-default value judgment — approved as deferred, see `docs/milestones/M9.md` §9.2); an explicit "reopen" Admin API endpoint (the schema no longer forecloses a second review, but nothing yet exposes a code path that creates one on request); a generic "list all Verdicts" endpoint; review-queue-depth metrics on `GET /v1/admin/metrics` (declined on direct precedent from M8's own restraint); SLA/timeout auto-escalation; bulk claim/resolve; cross-verdict/cross-finding aggregation of the review queue; the two pre-existing defects confirmed above (see Fixed). Compliance Dashboard (M10), encryption at rest (M11), Reporting (M12).

## [0.9.0-m8] — 2026-07-28 — M8: Evaluation Framework

Delivers architecture §10 ("Evaluation Framework"): a second concrete
population-level policy (`DisparitySignificanceTestPolicy`, a
two-proportion statistical-significance test — genuinely different in
kind from M6's ratio threshold, not a second variant of it) and
admin-configurable parameters (thresholds, minimum sample sizes) per
`population_policy_binding`, resolved with a documented fallback to each
policy's own built-in defaults. No new plugin port, no new persisted-
output table, no rewrite of the Event Lake read pattern. Full design
rationale, the twenty-one design decisions (twelve original plus four
found during the design-phase hostile-review pass, plus three more
resolved during implementation), and the post-implementation
production-readiness review: [`docs/milestones/M8.md`](docs/milestones/M8.md).

### Added
- `population_engine/policies/disparity_significance_test.py` — `DisparitySignificanceTestPolicy`: a two-proportion z-test comparing each `DIRECT`-classified protected-attribute value's favorable-outcome rate against the reference (highest-rate) value's rate, `FLAGGED` if `|z| >= z_critical` (default `2.0`, the *Castaneda v. Partida* "two or three standard deviations" convention). No new external dependency — closed-form arithmetic. Two statistical-validity guards beyond a flat sample-size floor, found during this milestone's own hostile-review pass: an expected-cell-count check (`favorable_outcome_count >= 5` and `total_count - favorable_outcome_count >= 5` for both compared groups) and a degenerate-variance guard.
- `population_engine/policies/_shared.py` — `group_by_attribute`, the one grouping helper genuinely shared between the two concrete population policies now that a second, real caller exists.
- `PopulationWindow.parameters`, `PopulationFinding.parameters_used`, `PopulationPolicyBinding.parameters` — admin-configurable overrides threaded from a binding through to the effective values a policy actually used, resolved by `run_policies.py` immediately before `evaluate()`, not through a widened port signature.
- `PopulationPolicyBindingRepository.get_active_by_identity` — a new, additional method (not a change to `get_by_identity`'s existing, lifecycle-blind semantics), used by `api/admin/population_policy_bindings.py`'s conflict check so a deactivated binding no longer blocks recreating one for the same `(system_id, population_policy_id)` pair.
- Migrations `0020`–`0022` — `population_policy_bindings.parameters` (nullable), `population_findings.parameters_used` (nullable, deliberately un-backfilled — see Fixed below), and a partial unique index (`one_active_population_policy_binding_per_system`, scoped to `ACTIVE`) replacing `population_policy_bindings`' previous plain `UNIQUE` constraint — the first migration since M1 to alter rather than only add to an existing table's constraints.

### Changed
- `population_engine/policies/adverse_impact_ratio.py` — resolves `threshold`/`minimum_group_size` from `window.parameters` with fallback to the exact pre-M8 hardcoded defaults and range validation; records `parameters_used`. A binding with no `parameters` produces byte-for-byte identical output to before M8 — additive capability, no version bump.
- `api/admin/population_policy_bindings.py` — request/response bodies gain an additive `parameters` field; conflict check switched from `get_by_identity` to `get_active_by_identity`.
- `audit/verify_population_findings.py` — `population_finding_hash` now dumps with `exclude_none=True` (see Fixed below).
- `plugins/bootstrap.py` — imports `disparity_significance_test`; `plugins/seed_registry.py` needed no change at all, since it already seeds every `known_population_policy_keys()` generically.

### Fixed
_(found during this milestone's own design-phase and implementation-time hostile-review passes, before freeze)_
- The original design draft specified `parameters_used` as an always-present field, backfilled `NOT NULL DEFAULT '{}'`. Since `population_finding_hash` hashes the entire model, this would have changed the recomputed hash — and silently invalidated the signature — of every `PopulationFinding` signed before this field existed, the first time `verify_population_findings` ran after M8 shipped. Fixed before implementation: `parameters_used` is nullable, never backfilled, and excluded from the hash when absent (`exclude_none=True`) — a pre-M8 record now hashes identically to how it was originally signed. Verified directly: a finding built exactly as pre-M8 code would have built it (no `parameters_used` constructed at all) still verifies against its original signature after this milestone's code and migrations.
- The original design draft's constraint relaxation (migration `0022`) was, on its own, a no-op fix: `create_population_policy_binding`'s conflict pre-check called `get_by_identity`, which ignores `lifecycle_state` and would still `409` a recreate attempt against a deactivated binding regardless of what the database constraint allowed. Fixed before implementation: a new `get_active_by_identity` method, used by the endpoint's conflict check instead — both the migration and this code change ship together, since neither alone is a complete fix.
- `DisparitySignificanceTestPolicy`'s first implementation reused `AdverseImpactRatioPolicy`'s flat `minimum_group_size` floor with no further guard — a group could clear that floor on raw count alone while still having a rate too extreme (e.g. 40 decisions at a 3% approval rate) for the two-proportion z-test's normal approximation to be statistically valid. Fixed during implementation: an additional expected-cell-count eligibility check, found by scrutinizing the z-test math itself, not just its plumbing.
- Confirmed, not changed: a genuinely pre-existing, previously-undiscovered defect in `policy_bindings` (M5) — the identical lifecycle-blind conflict check and identical plain (non-partial) uniqueness constraint `population_policy_bindings` had before this milestone's fix, meaning `PolicyBinding.severity` has likely never actually been changeable via "deactivate and recreate" in this platform's history. Left unfixed inside M8 (M5's scope, not the Evaluation Framework) — documented as a candidate for a small, dedicated follow-up.
- Confirmed, not changed: `db/migrate.py` runs every migration inside one transaction, so migration `0022` cannot use `CREATE INDEX CONCURRENTLY` (illegal inside a transaction block) — verified against the runner's actual code. The plain, blocking form is used deliberately, justified by `population_policy_bindings`' small, bounded, low-write-volume shape.
- **Post-freeze addendum:** the Admin API accepted a non-finite (`NaN`/`Infinity`) `parameters` override at binding-creation time with no rejection, persisting it as a genuine `NaN` in Postgres (verified directly by posting a raw `NaN` JSON literal — the HTTP response rendered it back as `null` only because Pydantic's JSON-mode serialization maps non-finite floats to `null`, not because a `null` was actually stored). Initially left deliberately unfixed on this review's own initiative, reasoning that §4.7/§13.2's design boundary ("no parameter validation in the API layer") covered it — re-evaluated on explicit request and corrected: that boundary was specifically about *per-metric semantic* range validation (`threshold` must be in `(0, 1]`), which does require knowing which policy a binding is for; rejecting a value that's never valid for *any* policy's *any* parameter requires no such knowledge and does not reopen the design. Fixed with an explicit `HTTPException` check in `create_population_policy_binding` (`_reject_non_finite_parameters`) — not a Pydantic `field_validator`, which was tried first and found to have a real framework interaction of its own: raising `ValueError` from a validator still lets FastAPI's request-validation machinery echo the raw invalid value into a structured error response, which Starlette's `JSONResponse` (`allow_nan=False`) then fails to serialize, surfacing a confusing `"Out of range float values are not JSON compliant"` message instead of a clear one.

### Deferred
Two additive nullable columns and one non-purely-additive constraint change (migration `0022`, narrowly scoped and justified — see `docs/milestones/M8.md` §4.4/§13.12); no existing table's meaning otherwise altered. A cross-policy aggregation mechanism for population findings (each stays independent and parallel — see `docs/milestones/M8.md` §13.5); per-event `Policy` configurability (this milestone's parameters mechanism is scoped to `PopulationPolicy` only); a third or fourth statistical test, or a genuinely pluggable "bring your own metric" surface; a "what-if, recompute under different parameters" capability (`population_findings`' own unique constraint already prevents recomputing a past window under new parameters); an update-in-place endpoint for a binding's parameters (deactivate and recreate); the pre-existing `policy_bindings` (M5) recreate-after-deactivate defect (see Fixed above); authentication on the one endpoint this milestone modifies (still `M5+/M13`, now a five-consecutive-milestone-and-counting gap). Human Review Workflow (M9), Compliance Dashboard (M10), encryption at rest (M11), Reporting (M12).

## [0.8.0-m7] — 2026-07-28 — M7: Monitoring — Governance & System Health

Delivers architecture §9 ("Monitoring"): a real readiness check
(`GET /readyz`, additive alongside the unchanged `/healthz`) and a single,
DB-query-backed metrics endpoint (`GET /v1/admin/metrics`) exposing
system-health (current-state) and governance-health (time-windowed)
signal over data every prior milestone already produces — no new
persisted domain state, no dashboard/UI, no metrics-store technology.
Full design rationale, the seventeen design decisions (fourteen original
plus three found during the design-phase hostile-review pass), and the
post-implementation production-readiness review:
[`docs/milestones/M7.md`](docs/milestones/M7.md).

### Added
- `api/readiness.py` — `GET /readyz`: a read-only database-connectivity check (reads one row from `systems`, not a bare `SELECT 1` — see Fixed below), `503` if unreachable. `/healthz` is unchanged.
- `observability/metrics.py` — `check_db_reachable`, `get_system_health_metrics`, `get_governance_health_metrics`, `get_metrics`; `SystemHealthMetrics` (DB reachability/latency, `evidence_chain`'s latest sequence number, plugin lifecycle counts, per-binding population-policy-run staleness), `GovernanceHealthMetrics` (verdict counts by status, finding counts by policy, population finding counts by policy, shadow/production disagreement rate — all scoped to `[since, now())`), `MetricsResponse`.
- `api/admin/metrics.py` — `GET /v1/admin/metrics?since=<ISO 8601>`, defaulting to the last 24 hours; a naive (non-timezone-aware) `since` is a `422`, the same discipline `schemas/decision_event.py`'s own validator already applies to persisted timestamps.
- Migrations `0017`–`0019` — indexes on `verdicts(created_at, status)`, `findings(evaluated_at, policy_id, outcome)`, `population_findings(population_policy_id, system_id, evaluated_at)`, supporting the new windowed-aggregate access pattern. No existing table altered.

### Changed
- `db/session.create_db_engine` — a bounded `connect_timeout` (found necessary while implementing the readiness check: an unreachable host can otherwise hang for the OS's full TCP-retransmission timeout, well over a minute, observed directly). Applies to every consumer of the shared engine — a strict improvement, not a narrowly-scoped fix.
- `pyproject.toml` — `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` now also lists `fastapi.Query` (alongside the existing `fastapi.Depends`), fixing a `ruff` false positive on `Query(default=None)` for a `datetime`-typed query parameter (the identical, already-passing call shape for a `str`-typed one is unaffected either way).
- `api/health.py`, `observability/__init__.py` — docstrings updated to name the real, now-delivered readiness check and metrics module, replacing the "future M7 work" framing both carried since M0/M6.

### Fixed
_(found during this milestone's own implementation and post-implementation hostile-review passes, before freeze)_
- Migration files applied via `db.migrate` are run through SQLAlchemy's `text()`, which parses a colon directly followed by a word as a bind parameter *even inside a SQL comment* — the first drafts of migrations `0017`–`0019` used phrasing like "since :since" in their own descriptive comments and failed to apply at all. Fixed by rewording; a warning is now left in migration `0017` for future migration authors.
- `check_db_reachable`'s first implementation ran a bare `SELECT 1`, which proves connectivity and authentication but nothing about whether the `gov_platform_app` role's actual table-level grants are intact — a role that could log in but had every grant revoked would still report "reachable." Fixed to read one row from `systems` instead.
- An unreachable database (a dropped route, not a fast "connection refused") could leave `/readyz` hanging past a minute before this milestone's `connect_timeout` fix — verified directly by connecting to a genuinely unreachable host during implementation, not assumed.

### Deferred
No schema changes beyond three additive indexes — every existing table kept its exact shape. A general, pluggable Evaluation Framework (M8; M7 exposes counts of judgments already computed, not new ones); a dashboard/UI (M10's Compliance Dashboard, not built here — see `docs/milestones/M7.md` §13.2); real metrics infrastructure (Prometheus/OpenTelemetry — no established scraping infrastructure exists to integrate with yet); caching/materialization of metrics (on-demand only this milestone); a sandbox-timeout counter (reversed out of scope entirely — a process-local metric would silently break under horizontal scaling, the one property every other metric in this design correctly avoids by being DB-backed); authentication on any endpoint, including the two new ones (still `M5+/M13`, now a four-milestone-and-counting gap). Human Review Workflow (M9), Compliance Dashboard (M10), encryption at rest (M11), Reporting (M12).

## [0.7.0-m6] — 2026-07-28 — M6: Async Population-Policy Evaluation Plane & Adverse Impact Ratio

Delivers the async evaluation plane population-level policies need — a
CLI-invoked batch job that evaluates many `DecisionEvent`s for one
`System` over one calendar-aligned window, entirely decoupled from, and
with zero effect on, the two existing synchronous ingestion routes — plus
one concrete population policy (adverse impact ratio, the EEOC "4/5ths
rule"). Full design rationale, the fourteen-plus-two original design
decisions, the hostile-review-pass corrections, and the production-
readiness review: [`docs/milestones/M6.md`](docs/milestones/M6.md).

### Added
- `population_engine/base.py` — `PopulationPolicy`, a third plugin port alongside `Adapter`/`Policy`; `PopulationWindow` (pre-aggregated `PopulationGroupCount` rows, not raw `DecisionEvent`s); `PopulationGroupCount`.
- `population_engine/window.py` — the "Event Lake" read path: builds a `PopulationWindow` from `decision_events`/`protected_attribute_refs` and the DB-backed `protected_attribute_rules`, under `REPEATABLE READ`. No new storage — a new windowed query over the existing normalized tables.
- `population_engine/policies/adverse_impact_ratio.py` — `AdverseImpactRatioPolicy`, the one concrete population policy: flags a `DIRECT`-classified protected attribute's value when its favorable-outcome-rate ratio (against the highest-rate value for that attribute) falls under 0.8, among values with at least 30 decisions in the window.
- `population_engine/run_policies.py` — `python -m gov_platform.population_engine.run_policies`, the batch CLI: for each active `PopulationPolicyBinding` with a `PRODUCTION` population policy, builds a fixed, calendar-aligned, closed-in-the-past window (default: yesterday's full UTC day; `--window-start`/`--window-end` override together), evaluates it under `run_sandboxed`, signs it, and persists it. One binding's failure is reported and does not abort the rest of the run.
- `schemas/population_finding.py`, `schemas/population_policy_binding.py` — `PopulationFinding` (not `decision_event_id`-keyed — an aggregate result over many decisions), `PopulationFindingOutcome` (`CLEAR`/`FLAGGED`), `PopulationPolicyBinding` (`system_id`-keyed, not `adapter_id`-keyed), `PopulationPolicyBindingLifecycleState` (`ACTIVE`/`INACTIVE`).
- `db/repositories/population_finding.py`, `db/repositories/population_policy_binding.py`; `api/admin/population_findings.py` (`list`/`get`, read-only — a population finding is only ever produced by the batch job) and `api/admin/population_policy_bindings.py` (`create`/`list`/`get`/`activate`/`deactivate`). Migrations `0014`–`0016`.
- `audit/verify_population_findings.py` — `population_finding_hash` (a plain content hash, not `hash_chain`'s chained variant — population findings aren't chained, see §13.5) and a standalone verification CLI, shipped alongside signing rather than deferred (signing with no verifier would be exactly the "infrastructure with zero callers" pattern this milestone's own read API argued against).
- `PluginType.POPULATION_POLICY` — a `PopulationPolicy` registers/promotes through the exact same `plugin_registrations` lifecycle every `Adapter`/`Policy` already uses; no second lifecycle mechanism.
- `PopulationFinding.classification_snapshot` — every finding embeds exactly which `protected_attribute_rules` classifications it was computed against, independent of later edits to that (live, admin-mutable) table. The reproducibility fix from this milestone's hostile-review pass (§13.16): without it, a historical finding would silently drift with whatever the ruleset says today, rather than reproducing what was originally reported.

### Changed
- Nothing. `POST /v1/ingestion/events`, `POST /v1/ingestion/events/credit-scorecard`, `Adapter`, `Policy`, `GovernanceEngine`, and `EvidenceStore.append` are byte-for-byte unchanged — the async plane this milestone builds is additive and parallel, not a redesign of per-event ingestion (see §13.1's central, highest-stakes call).
- `plugins/seed_registry.py` — also seeds `adverse-impact-ratio` to `PRODUCTION`. Deliberately does **not** seed a `PopulationPolicyBinding`: unlike `adapter_id` (a fixed identity every registered `Adapter` already has), `population_policy_bindings.system_id` requires a real `System` row nothing guarantees exists at seed time — binding the policy to a real system is a genuine operator decision, left to `POST /v1/admin/population-policy-bindings`.

### Fixed
_(found during this milestone's own hostile-review and production-readiness passes, before freeze)_
- The original design draft had `population_engine/window.py` resolving attribute values from `protected_attribute_resolutions`, which only ever holds *classification* (`DIRECT`/`PROXIED`/`WITHHELD`), never the attribute's actual value — adverse impact ratio groups decisions *by value*. Fixed before implementation: values now come from `decision_events.protected_attribute_refs` directly.
- The original draft proposed no locking and left window semantics (`window_start`/`window_end` selection) completely unspecified — a rolling, `now()`-relative window would have made the `UNIQUE` constraint meaningless and produced redundant/racy findings under any repeated invocation. Fixed before implementation: fixed, calendar-aligned, closed-in-the-past windows; `REPEATABLE READ` for window-building reads; `UNIQUE (population_policy_id, system_id, window_start, window_end)`.
- The original draft proposed ordinary (mutable) database privileges for `population_findings` and no verifier for its signatures. Fixed before implementation: `population_findings` is append-only (`REVOKE UPDATE, DELETE`, migration `0015`) and `audit/verify_population_findings.py` ships alongside signing.
- `policy_engine/__init__.py`'s module docstring still named population-level policies as future M6/M8 work after this milestone delivered them (for the concrete-policy half; the framework half is still M8) — updated to the real, current state. The same class of finding M4's and M5's own reviews each caught in a handful of other files.

### Deferred
Three new migrations (`0014`–`0016`): two new tables (`population_policy_bindings`, `population_findings`) and one new index (`decision_events(model_version_id, occurred_at)`, required for the one new windowed-read access pattern this milestone introduces) — no existing table altered. A general, pluggable Evaluation Framework (M8; this milestone ships one concrete metric, not the framework); real scheduling of the batch job (cron/`CronJob`, deployment-topology scope, M13-adjacent); a dedicated analytical store for the "Event Lake" (the existing operational tables are reused, not duplicated); severity/escalation for population findings (stay purely informational — there is still no Human Review Workflow, M9, for *any* escalated output to go to); redesigning per-event ingestion into a queued/polled contract (explicitly declined, §13.1); recomputing a historical window under today's rules (a distinct "what-if" capability, not built); authentication on any endpoint, including this milestone's two new admin surfaces (still `M5+/M13`, flagged more sharply than at any prior milestone — see `docs/milestones/M6.md` §13.14). Human Review Workflow (M9), Compliance Dashboard (M10), encryption at rest (M11).

## [0.6.0-m5] — 2026-07-27 — M5: Policy Bindings, Verdict Escalation & Evidence Signing

Replaces the static, code-defined `Adapter.governing_policy_ids` with a
database-backed Policy Binding, gives `GovernanceEngine` the full
four-state `VerdictStatus` driven by per-binding severity, signs every
evidence record, and moves protected-attribute classification rules
off static code for `EvidenceStore`'s resolution path. Full design
rationale, decisions, and the production-readiness review:
[`docs/milestones/M5.md`](docs/milestones/M5.md).

### Added
- `schemas/policy_binding.py` — `PolicyBinding`, `PolicySeverity` (`LOW`/`MEDIUM`/`HIGH`), `PolicyBindingLifecycleState` (`ACTIVE`/`INACTIVE`); `db/repositories/policy_binding.py`; `api/admin/policy_bindings.py` (`create`/`list`/`get`/`activate`/`deactivate`). Migration `0011`.
- `schemas/protected_attribute_rule.py` — `ProtectedAttributeRule`, `ProtectedAttributeRuleClassification` (`DIRECT`/`PROXY`); `db/repositories/protected_attribute_rule.py`; `api/admin/protected_attribute_rules.py` (`create`/`list`/`get`). Migration `0012`.
- `audit/signing.py` — Ed25519 evidence-record signing/verification (`EvidenceSigner`, `load_signer`, `verify_signature`); a small CLI to derive a public key from a private key. `evidence_chain` gains nullable `signature`/`signing_key_id` columns (migration `0013`).
- `VerdictStatus.ALLOW_WITH_FLAG`, `.ESCALATE_FOR_REVIEW`, `.RECOMMEND_HOLD` — the real four-state model. `.ALLOW`/`.FLAGGED` are kept as permanent, historical-only members for pre-M5 rows.
- `GovernanceEngine(governing_policies: list[GoverningPolicy])` — `GoverningPolicy` bundles a `Policy` with its binding's `PolicySeverity`; aggregation is highest-flagged-severity-wins, mapped to the four-state status.

### Changed
- `Adapter.governing_policy_ids` **removed** — which policies govern an adapter is now resolved per-request from `policy_bindings` (`PolicyBindingRepository.list_active_for_adapter`), admin-managed without a redeploy. `plugins/seed_registry.py` seeds the equivalent bindings for both first-party adapters, reproducing M0–M4 behavior exactly at cutover.
- `protected_attributes/resolver.py` — `ProtectedAttributeResolver` gains an optional `engine` constructor parameter; when given, rules come from the DB-backed `protected_attribute_rules` table instead of `classification.py`'s static dict. `EvidenceStore` now constructs it with its own `Engine`; `DirectAttributeInInputsPolicy` is unchanged, a deliberate, named divergence (see M5's design doc §13.9).
- `EvidenceStore.append` signs every record's `record_hash` before persisting; `EvidenceRecord` gains `signature`/`signing_key_id` (both `None` for pre-M5 rows). `verify_chain`/its CLI gain an optional `--public-key` to also verify signatures.
- `api/ingestion/routes.py`'s per-request policy resolution now queries `policy_bindings` instead of a class attribute; an adapter with zero active bindings fails with a 503.

### Fixed
_(found during this milestone's own production-readiness review, before freeze)_
- `protected_attributes/classification.py`'s module docstring still described DB-backed rules as entirely future work after this milestone partially delivered them — updated to name the real, scoped-to-one-consumer state.

### Deferred
No schema changes were needed beyond three additive migrations (two new tables, two nullable columns) — every existing table kept its shape. Domain/jurisdiction-keyed Policy Bindings (only `adapter_id`-keyed shipped), unifying `DirectAttributeInInputsPolicy` with DB-backed rules, signing-key rotation/KMS custody, and authentication on any endpoint (including the two new M5 admin routes) all remain named, deferred gaps — see `docs/milestones/M5.md` §15/§16. Human Review Workflow (M9), Compliance Dashboard (M10), encryption at rest (M11), async ingestion (M6).

## [0.5.0-m4] — 2026-07-27 — M4: Policy Plurality & Disagreement Surfacing

`GovernanceEngine` now runs more than one `Policy` against a single
Decision Event and aggregates their Findings into one Verdict — the
platform's first real multi-policy governance decision. Full design
rationale, decisions, and the production-readiness review:
[`docs/milestones/M4.md`](docs/milestones/M4.md).

### Added
- `policy_engine/policies/high_debt_ratio_gate.py` — the second real policy: a plain `debt_to_income` threshold gate (CFPB ATR/QM's 0.43, cited for concrete provenance), deliberately not another fairness check.
- `GovernanceEngine(policies: list[Policy])` — aggregates via any-`FLAGGED`-wins; raises `ValueError` for an empty list; a raising policy propagates uncaught rather than producing a partial verdict.
- `Adapter.governing_policy_ids: tuple[str, ...]` — widened from M3's singular `governing_policy_id`, still static and code-defined (dynamic, admin-managed binding remains M5's Policy Bindings, not this).

### Changed
- `CreditScorecardAdapter` retrofitted to `0.2.0`, now governed by both `direct-attribute-in-inputs` and `high-debt-ratio-gate` — registered and promoted through the existing M3 plugin lifecycle, not a silent change to what `0.1.0` meant while `PRODUCTION`. Verified live: promoting `0.2.0` correctly auto-demoted `0.1.0` to `SHADOW`.
- `api/ingestion/routes.py`'s per-request policy resolution now loops over every declared governing policy family, collecting all `PRODUCTION` policies into one `GovernanceEngine`; any family missing one fails the whole request.
- `db/repositories/verdict.py`'s read order gains `policy_id` as a secondary sort key, closing a rare tie-break gap now that a verdict can have more than one finding.
- `SyntheticAdapter` — mechanical `governing_policy_id` → `governing_policy_ids` update, no version bump, no behavior change.

### Fixed
_(found during this milestone's own production-readiness review, before freeze)_
- Several module docstrings (`governance_engine/__init__.py`, `policy_engine/__init__.py`, `api/admin/__init__.py`) still described policy plurality and Admin API scope in future tense after this milestone made them real — updated to the current, accurate state.

### Deferred
No schema changes were needed this milestone — `verdict_findings` and the repository layer were built with plurality in mind since M1. No new Admin API surface was needed either — an adapter's governing policies stay static, administered through M3's existing plugin registry endpoints. See `docs/milestones/M4.md` for the full account. Policy Bindings and the full four-state verdict model (M5), async ingestion and population-level policies (M6), encryption at rest (M11).

## [0.4.0-m3] — 2026-07-26 — M3: Plugin Registry, Lifecycle & Sandboxing

Replaces M2's two hand-wired adapter/policy pairs with a real plugin
registry: adapters and policies are registered with a draft/shadow/
production lifecycle, ingestion routes are generated from whatever is
registered, and every plugin call runs under a timeout + exception-
isolating sandbox. Full design rationale, decisions, and the production-
readiness review: [`docs/milestones/M3.md`](docs/milestones/M3.md).

### Added
- `plugins/registry.py` + `plugins/bootstrap.py` — an in-process catalog of first-party `Adapter`/`Policy` implementations, populated by `@register_adapter`/`@register_policy` decorators at import time. Not dynamic/external code loading.
- `plugins/sandbox.py` — `run_sandboxed`, a timeout + exception-isolation wrapper around every plugin call. Deliberately not process/container isolation (no untrusted third-party plugin author exists yet).
- `schemas/plugin_registration.py` + migration `0010` — `plugin_registrations` (draft/shadow/production lifecycle, a database constraint enforcing at most one `PRODUCTION` version per plugin) and `shadow_findings` (a shadow policy's output, structurally separate from `findings`).
- `api/admin/plugins.py` — register/list/get/promote a plugin's lifecycle state, rejecting any `plugin_id`/`version` this process's code hasn't registered in-process.
- `plugins/seed_registry.py` — a CLI that seeds the first-party plugins to `PRODUCTION`, kept separate from `create_app()` to preserve its DB-free-construction invariant.
- `api/ingestion/routes.py` rewritten — one real, independently-typed FastAPI route generated per registered adapter, preserving Pydantic validation and OpenAPI generation, instead of one hand-written route per adapter.
- `adapters/base.py` gains `adapter_id`/`version`/`governing_policy_id` identity, mirroring `Policy`'s existing `policy_id`/`version`.

### Changed
- `SyntheticAdapter`, `CreditScorecardAdapter`, `AlwaysAllowPolicy`, `DirectAttributeInInputsPolicy` are now registered plugins, retrofitted into the registry as its first four entries. `api/app.py`'s hand-wiring of them is gone entirely.
- `Policy.evaluate(event) -> Finding` and `Adapter.translate` are unchanged — shadow execution is a side channel the ingestion route manages directly, not a widened port contract.

### Fixed
_(found during this milestone's own production-readiness review, before freeze)_
- The most literal reading of "generate routes from PRODUCTION adapters" would have required a live database read at `create_app()` construction time, breaking the DB-free-construction invariant every milestone since M0 has relied on. Resolved by generating route *existence* from the in-process registry and resolving *which policy governs a request* from the database per-request instead.
- `create`/`promote` on the plugin registry could surface a genuine database race (two concurrent callers registering/promoting the same identity) as a raw `500` instead of a clean client error — fixed by catching the constraint violation and re-raising a `ValueError`, the same client-error category already established in M2.

### Deferred
See `docs/milestones/M3.md` for the full account, including an accepted, documented inconsistency (the Admin API's own pre-check returns `409` for the common duplicate-registration case, while the rare race that slips past it returns `422`) and one production-readiness finding intentionally left untested (a two-thread test for `promote()`'s race branch was attempted and found to assert a false invariant under low contention). Policy plurality (M4), the full four-state verdict model (M5), DB-backed classification rules (M5), real OS-level plugin isolation (unscheduled), encryption at rest (M11).

## [0.3.0-m2] — 2026-07-26 — M2: Protected Attribute Resolution, First Real Adapter & Judgment-Bearing Policy

Formalizes Protected Attribute Resolution (direct/proxied/withheld) and
ships the platform's first real, non-synthetic adapter (a classical-ML
credit scorecard) and its first genuinely judgment-bearing policy — one
that can actually produce `FLAGGED`. Full design rationale, decisions, and
the production-readiness review: [`docs/milestones/M2.md`](docs/milestones/M2.md).

### Added
- `schemas/protected_attribute.py` — `ProtectedAttributeClassification` (`DIRECT`/`PROXIED`/`WITHHELD`) and `ResolvedProtectedAttribute`, a value object kept separate from `DecisionEvent` rather than a new field on it.
- `protected_attributes/` — `ProtectedAttributeResolver` (a concrete service, not a plugin port) and a static, code-defined `FINANCE` classification ruleset.
- `adapters/credit_scorecard.py` — `CreditScorecardAdapter`, the second real `Adapter` implementation, proving `Adapter[TPayload]`'s port generalizes beyond `SyntheticAdapter`.
- `policy_engine/policies/direct_attribute_in_inputs.py` — `DirectAttributeInInputsPolicy`, flags a Decision Event when a `DIRECT`-classified protected attribute leaks into the model's own `input_features`. Holds `ProtectedAttributeResolver` as a constructor collaborator; `Policy.evaluate(event) -> Finding`'s signature is unchanged.
- Migration `0009` and `db/repositories/protected_attribute_resolution.py` — a sixth table/repository, written atomically inside `EvidenceStore.append`'s existing transaction.
- `POST /v1/ingestion/events/credit-scorecard` — a second ingestion route, its own adapter and independently-policied `GovernanceEngine`, sharing the same `EvidenceStore` and `NormalizationService` as the original, byte-for-byte-unchanged route.

### Fixed
_(found during this milestone's own production-readiness review, before freeze)_
- An unrecognized protected attribute (structurally valid, semantically rejected by `ProtectedAttributeResolver`) surfaced as a raw `500` instead of a `422` — fixed with a dedicated `ValueError` exception handler in `api/app.py`, the same client-error category Pydantic's own validation errors already get.

### Deferred
See `docs/milestones/M2.md` for the full account, including two documented (not fixed) limitations: the policy's fixed `FINANCE` domain can diverge from what `EvidenceStore` actually persists for an auto-provisioned (never pre-registered) system, and domain-name matching is case-sensitive with no normalization. Plugin registry/discovery/sandboxing (M3), policy plurality (M4), the full four-state verdict model (M5), async ingestion (M6), DB-backed classification rules (M3/M5), encryption at rest (M11).

## [0.2.0-m1] — 2026-07-26 — M1: Postgres Persistence & System Registry, verified

Originally built "CI-verified, locally skip-if-absent" (no Postgres/Docker
in that sandbox); with Docker Desktop and WSL now installed, the milestone
has been re-verified end to end against a real Postgres 16 container,
exactly mirroring `.github/workflows/ci.yml`. See
[`docs/milestones/M1.md`](docs/milestones/M1.md)'s "verified against real
Postgres" update for the full account.

### Fixed (found only once real Postgres execution became possible)
- `db/migrate.py`'s `create_engine()` on a bare `postgresql://` URL defaulted to the uninstalled `psycopg2` driver instead of this project's actual dependency, `psycopg` (v3) — migrations could not run at all. Fixed by normalizing the URL's driver inside `migrate.py`.
- `infra/ci/setup_test_role.py`'s `ALTER ROLE ... PASSWORD %s` was a Postgres syntax error — DDL's `PASSWORD` clause requires a literal, not a bind parameter. Fixed with `psycopg.sql.Literal`.
- `test_body_within_limit_is_not_rejected_by_the_middleware` reused a fixture with a hardcoded `source_event_id`, unlike every other M1 test file — since `decision_events.id` is a permanent primary key, it could only pass once per database lifetime. Fixed to generate a unique id.
- Coverage floor (98%) failed at 92% on first real measurement: several genuine, reachable code paths (`DecisionEventRepository.get`, `FindingRepository.list_by_decision_event`, `ModelVersionRepository.get`/`list_by_system`, `VerdictRepository.get`, `verify_chain_from_database`, both CLI `main()` wrappers) had no test coverage. Added integration/unit tests for all of them; added a standard `[tool.coverage.report]` exclusion for the two genuinely-unreachable `abc.abstractmethod` bodies and two `if __name__ == "__main__":` guards. Coverage is now 100%.

## [0.2.0-m1] — 2026-07-26 — M1: Postgres Persistence & System Registry (original)

Replaces M0's SQLite placeholder with a real Postgres operational store and
hash-chained evidence ledger, formalizes System/ModelVersion entities, and
enforces evidence append-only-ness at the database-privilege level. Built
"CI-verified, locally skip-if-absent": this sandbox has no Postgres/Docker,
so DB-dependent code is written to production standard and verified in CI's
real Postgres service container, not executed in this session — see
[`docs/milestones/M1.md`](docs/milestones/M1.md) for exactly what that means
and what to watch on the first CI run.

### Added
- `System` and `ModelVersion` canonical schemas, replacing M0's bare `system_id` string.
- 8 Postgres migrations (`infra/migrations/0001`–`0008`): systems, model_versions, decision_events, findings, verdicts, verdict_findings, evidence_chain, and DB-privilege grants.
- A minimal migration runner (`db/migrate.py`) — no Alembic, consistent with M0's tooling discipline.
- A repository layer (`db/repositories/`) — one class per entity, session-parameterized for cross-table transactional atomicity.
- `audit/hash_chain.py`, extracted from `evidence_store.py` per the frozen file list.
- `audit/verify_chain.py` — standalone hash-chain verification job (pure core + CLI).
- Admin API (`api/admin/systems.py`) — register/list/get a System, stricter (409 on duplicate) than ingestion's auto-provisioning.
- CI now runs a real Postgres 16 service container, applies migrations, and enforces the coverage floor there.

### Changed
- `EvidenceStore` reimplemented on Postgres — same public interface (`append`/`get`/`all`/`EvidenceRecord`) as M0, entirely different internals: normalized writes through five repositories, `pg_advisory_xact_lock` for cross-instance-correct concurrency (replacing M0's in-process-only lock), database-privilege-enforced append-only (`REVOKE UPDATE, DELETE`) replacing M0's application-layer stopgap.
- `EvidenceStore`'s constructor now takes an `Engine`, not a SQLite path — enables connection-pool sharing with the new Admin API.
- `Settings.EVIDENCE_DB_PATH` removed, replaced by `Settings.DATABASE_URL`.
- Coverage floor (`--cov-fail-under=98`) moved from always-enforced locally to CI-only — a real chunk of M1's code is legitimately Postgres-only and cannot execute in this sandbox.
- `decision_events.id` (`DecisionEvent.event_id`) is now a real primary key — a deliberate new uniqueness constraint M0's blob table never enforced.

### Fixed
_(caught mid-implementation, before ever reaching CI)_
- The originally planned concurrency mechanism (`SELECT ... FOR UPDATE`) was found to require UPDATE privilege in Postgres, directly conflicting with the `REVOKE UPDATE` the append-only guarantee depends on — replaced with `pg_advisory_xact_lock`, which needs no table privileges at all. See `docs/milestones/M1.md`.
- A cross-class access to a "private" `_to_model` method (`FindingRepository` from `VerdictRepository`) was made properly public instead.
- A stub `DecisionEventRepository.get()` would have crashed on every call (constructing `DecisionEvent` with an invalid empty `system_id`) — fixed with a proper join back to `systems.name`.

### Deferred
See `docs/milestones/M1.md` for the full table with milestone ownership: Protected Attribute Resolution and a real adapter (M2), plugin architecture (M3), policy plurality (M4), the full Verdict state machine and signing (M5), async ingestion and population-level policies (M6), encryption at rest and retention (M11), comprehensive request-abuse protection (M13).

## [0.1.0-m0] — 2026-07-26 — M0: Repository Foundation & Walking Skeleton

A complete, real vertical slice through every architectural seam — adapter,
normalization, policy engine, governance engine, evidence store, API —
establishing the foundation every later milestone builds on additively.
Full details: [`docs/milestones/M0.md`](docs/milestones/M0.md).

### Added
- Canonical domain schemas: `DecisionEvent`, `Finding`, `GovernanceVerdict`.
- `Adapter[TPayload]` port (generic, ABC-based) and reference implementation `SyntheticAdapter`.
- `NormalizationService` (structural normalization only).
- `Policy` port and reference implementation `AlwaysAllowPolicy`.
- `GovernanceEngine`, wrapping a single `Policy`'s `Finding` into a `GovernanceVerdict`.
- `EvidenceStore` — SHA-256 hash-chained, SQLite-backed, append-only audit ledger.
- FastAPI service: composition-root `create_app` factory, `GET /healthz`, `POST /v1/ingestion/events`.
- Global unhandled-exception handler (no more leaked tracebacks to clients).
- `MaxBodySizeMiddleware` — rejects oversized requests via `Content-Length`.
- Structured JSON logging (stdlib-only).
- Full tooling: `ruff`, `mypy --strict`, `pytest` with enforced coverage floor, `pre-commit`, GitHub Actions CI, `Dockerfile` / `docker-compose.yml`, `requirements-lock.txt`.
- `docs/architecture-mapping.md` and `docs/milestones/M0.md`.

### Changed
- V1 prototype (`app.py`, `governance.py`, `causal_engine.py`, etc.) archived unmodified to `legacy_v1/` — superseded by this design, not deleted.

### Fixed
_(resolved during the pre-freeze production-readiness review, before ever shipping)_
- Ingestion route ran fully synchronous code inside `async def`, blocking the event loop under concurrent load — changed to a plain `def` handler.
- No request body size limit on the Ingestion API — added `MaxBodySizeMiddleware`.
- `Adapter.translate` typed its payload as `Any`, discarding type safety at the port boundary — made `Adapter` generic.
- Dependency providers typed against the concrete `SyntheticAdapter` instead of the `Adapter` abstraction — corrected the one genuine DIP violation.
- No coverage regression gate — added `--cov-fail-under=98`.
- No pinned dependency lockfile — added `requirements-lock.txt`, verified from a clean environment.
- `EvidenceStore`'s concurrency-safety claim (an in-process lock) was undocumented by any test — added a concurrent-writer test proving a single valid hash chain.

### Deferred
See `docs/milestones/M0.md` for the full table with milestone ownership: Postgres migration and DB-privilege immutability (M1), Protected Attribute Resolution and a real adapter (M2), plugin architecture (M3), policy plurality (M4), the full Verdict state machine and signing (M5), async ingestion and population-level policies (M6), encryption at rest and retention (M11), comprehensive request-abuse protection (M13).
