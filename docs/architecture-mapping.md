# Architecture → Module Mapping (M8)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M8 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + two implementations. **Unchanged by M6** — both ingestion routes, and everything downstream of them, are byte-for-byte identical to M5 (see M6-specific notes: the async plane M6 builds is additive and parallel, not a change to per-event ingestion). |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M6. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py`, `schemas/protected_attribute_rule.py`, `db/repositories/protected_attribute_rule.py` | Unchanged by M6 for this service itself. **M6 adds a third, read-only consumer** of the DB-backed `protected_attribute_rules` table (`population_engine/window.py`, via its own direct repository call, not through `ProtectedAttributeResolver`) — see M6-specific notes on why, and on the reproducibility consequence that creates. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py`, `population_engine/base.py`, `plugins/registry.py`, `plugins/bootstrap.py`, `plugins/sandbox.py`, `schemas/plugin_registration.py`, `db/repositories/plugin_registration.py`, `api/admin/plugins.py` | In-process registry + database-backed lifecycle state + a timeout/exception-isolation sandbox around every plugin call. **New in M6**: `PluginType.POPULATION_POLICY` — a third plugin kind, using the exact same registry/lifecycle mechanism `Adapter`/`Policy` already do, no second mechanism invented. `Adapter`/`Policy`/`PopulationPolicy` are now the three ports; Policy Bindings and Population Policy Bindings are separate, orthogonal axes (*which* trusted policies apply, not *whether* a policy's code is trusted). |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/*.py`, `schemas/policy_binding.py`, `db/repositories/policy_binding.py`, `api/admin/policy_bindings.py` | Real port + three reference policies, unchanged by M6. `Policy.evaluate(event) -> Finding`'s signature remains untouched — population-level evaluation is a deliberately separate, parallel port (`population_engine/base.py`, below), never a widened `Policy`. |
| §7/§8 Population-Level Policy Engine | `population_engine/base.py` (`PopulationPolicy`, `PopulationWindow`, `PopulationGroupCount`), `population_engine/window.py`, `population_engine/policies/adverse_impact_ratio.py`, `population_engine/policies/disparity_significance_test.py`, `population_engine/policies/_shared.py`, `population_engine/run_policies.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py`, `db/repositories/population_finding.py`, `db/repositories/population_policy_binding.py`, `api/admin/population_findings.py`, `api/admin/population_policy_bindings.py` | **New in M6, generalized at M8.** A third plugin port, `PopulationPolicy`, evaluating many `DecisionEvent`s for one `System` over one time window into one `PopulationFinding` — structurally parallel to, and never touching, `Policy`/`Finding`/`Verdict`. Two concrete policies ship: `adverse-impact-ratio` (M6, EEOC "4/5ths rule", 29 CFR § 1607.4(D)) and `disparity-significance-test` (M8, a two-proportion statistical-significance test, *Castaneda v. Partida* convention) — genuinely different kinds of judgment, proving the port generalizes, not a second ratio-threshold variant. **M8**: both policies' thresholds/minimum sample sizes are now admin-configurable per binding (`PopulationWindow.parameters`, resolved from the binding, with range validation and fallback to built-in defaults — see M8-specific notes), and `population_policy_bindings`' uniqueness is relaxed to a partial index scoped to `ACTIVE` (migration `0022`) so a binding can actually be deactivated and recreated with different parameters. Triggered by an explicitly-invoked batch CLI (`population_engine/run_policies.py`), not a daemon or in-process scheduler — this *is* "the async ingestion plane" (§4.1's citation), read as the plane population-level policies specifically need, not a redesign of per-event ingestion. `PopulationPolicyBinding` is `system_id`-keyed, a new table, deliberately separate from `policy_bindings`. See M6/M8-specific notes. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Unchanged by M6. `GovernanceEngine`/`GovernanceVerdict` remain per-event; population-level results never flow through them. |
| §9 Monitoring | `observability/logging.py`, `observability/metrics.py`, `api/readiness.py`, `api/admin/metrics.py` | **Real as of M7.** `GET /readyz` — a real readiness check (database connectivity only; "adapter/source reachability" is currently vacuous, no first-party `Adapter` has a real external dependency yet), additive alongside the unchanged `/healthz`. `GET /v1/admin/metrics?since=` — a single, DB-query-backed JSON aggregate of system-health (current-state) and governance-health (windowed) signal, no new persisted state, no Prometheus/OpenTelemetry, no dashboard/UI (see M7-specific notes). |
| §10 Evaluation Framework | `population_engine/policies/adverse_impact_ratio.py`, `population_engine/policies/disparity_significance_test.py`, `population_engine/policies/_shared.py` | **Real as of M8.** Two concrete, genuinely different statistical tests (a ratio threshold and a significance test) plus admin-defined thresholds per binding — the two things `architecture-mapping.md`'s own M6-era citation named as missing. Still not a "bring your own statistical test" plugin surface beyond these two — that remains unscheduled until a concrete third need appears (see `docs/milestones/M8.md` §15). |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9 — an `ESCALATE_FOR_REVIEW` verdict (M5) and a `FLAGGED` `PopulationFinding` from either population policy (M6/M8) are both fully computed and persisted; nothing yet queues either for a human to act on. Unchanged by M8: a second population policy that can also produce `FLAGGED` does not add a workflow for either one. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py`, `audit/signing.py`, `audit/verify_population_findings.py` | Real hash-chained Postgres ledger for per-event evidence, append-only enforced at the database-privilege level, plus a standalone chain-verification job/CLI — unchanged by M6/M8. **New in M6**: `population_findings` gets the identical append-only privilege lockdown (`REVOKE UPDATE, DELETE`, migration `0015`) and is signed (reusing `audit/signing.py` unchanged) — but is **not chained** into `evidence_chain` (no `previous_hash`, no single `decision_event_id` it belongs to). `audit/verify_population_findings.py` is a separate, parallel verifier — a plain content hash over each finding's own canonical payload (including `classification_snapshot`), not `hash_chain`'s chained variant. **New in M8**: `population_finding_hash` dumps with `exclude_none=True`, so `parameters_used` (nullable, un-backfilled, migration `0021`) is omitted from the hashed payload for every finding signed before this field existed, rather than changing their recomputed hash and silently invalidating their already-issued signatures — the first time this codebase has added a field to an already-populated signed model (see `docs/milestones/M8.md` §4.5/§13.18). Key rotation/KMS custody and retention tiers remain unassigned/M11 for both. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/readiness.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/admin/plugins.py`, `api/admin/policy_bindings.py`, `api/admin/protected_attribute_rules.py`, `api/admin/population_policy_bindings.py`, `api/admin/population_findings.py`, `api/admin/metrics.py`, `api/app.py`, `api/asgi.py` | Ingestion routes are registry-generated (one per registered adapter — currently `synthetic` and `credit-scorecard`), **unchanged by M7/M8**, same response shape; `/healthz` also unchanged. `GET /readyz` and `GET /v1/admin/metrics` (M7) unchanged by M8. **New in M8**: `POST /v1/admin/population-policy-bindings`'s request/response bodies gain an additive `parameters` field, and its conflict pre-check now calls the new `get_active_by_identity` (lifecycle-scoped) rather than the lifecycle-blind `get_by_identity` — the schema relaxation (migration `0022`) alone did not make a binding's parameters actually changeable without this. Still no `PATCH`/update endpoint. No endpoint anywhere has authentication yet, including this one — the same standing gap M5/M6/M7 named, now a five-consecutive-milestone-and-counting gap (see M8-specific notes). `app.py` is still the side-effect-free factory. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py`, `schemas/plugin_registration.py`, `schemas/policy_binding.py`, `schemas/protected_attribute_rule.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity. **New in M7**: three indexes (migrations `0017`–`0019`, on `verdicts`, `findings`, and `population_findings` respectively) supporting the new windowed metrics-aggregate read pattern — no new table, no existing table altered. **New in M8**: two additive nullable columns (`population_policy_bindings.parameters`, migration `0020`; `population_findings.parameters_used`, migration `0021`, deliberately un-backfilled — see §13 above) and one non-purely-additive change — `population_policy_bindings`' plain `UNIQUE (system_id, population_policy_id)` constraint relaxed to a partial unique index scoped to `ACTIVE` (migration `0022`), the first migration since M1 to alter rather than only add to an existing table's constraints, narrowly justified (see `docs/milestones/M8.md` §4.4/§13.12). `db/session.create_db_engine`'s bounded connection timeout (M7) unchanged. SQLAlchemy models are query-time mappings only — never used to generate DDL. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres — unchanged by M7/M8. A real orchestrator can use `GET /readyz` as an actual readiness probe rather than reusing `/healthz` (liveness only) for both purposes. Multi-plane topology, multi-tenancy, and mTLS are M13. |

## M8-specific notes

- **A generalization milestone, not a new pipeline.** M8 does to
  `population_engine` what M4 did to `Policy`/`GovernanceEngine` and M5
  did to `PolicyBinding`: ship a second concrete implementation of an
  already-general-enough port, and move a judgment call (a threshold)
  from code onto an admin-configurable binding. No new plugin port, no
  new persisted-output table, no rewrite of the Event Lake read pattern.
- **`DisparitySignificanceTestPolicy` is a genuinely different kind of
  judgment, not a second ratio-threshold variant.** A two-proportion
  z-test answers "is this disparity plausibly noise," where
  `adverse-impact-ratio` answers "is this disparity practically large" —
  the same "different kind of judgment" discipline M4 used picking
  `HighDebtRatioGatePolicy` over a second fairness-check variant. No new
  external dependency — the z-statistic is closed-form arithmetic.
- **Two statistical-validity guards beyond a flat sample-size floor**,
  found scrutinizing the z-test math during this milestone's own
  hostile-review pass: an expected-cell-count check (a group can clear
  `minimum_group_size` on raw count alone while still having a rate too
  extreme for the normal approximation to be valid) and a degenerate-
  variance guard (never actually reachable once the expected-cell-count
  check holds, kept as defense in depth).
- **Admin-configurable parameters thread through `PopulationWindow`, not
  a widened `evaluate()` signature.** `PopulationWindow` already existed
  to carry "everything this evaluation needs beyond the window's raw
  data" (`classification_snapshot` set this precedent at M6) — a
  `parameters` field is the same pattern for a second kind of context,
  not a new one. Each policy validates its own resolved parameters
  against a sane range, falling back to its built-in default rather than
  silently proceeding with a nonsensical value or raising.
- **The headline hostile-review-pass finding: adding a field to an
  already-signed, already-populated model is a genuinely new problem
  class for this codebase.** `parameters_used`'s first draft (an
  always-present field, backfilled `NOT NULL DEFAULT '{}'`) would have
  silently invalidated every `PopulationFinding` signed before M8 the
  first time `verify_population_findings` ran afterward — `population_finding_hash`
  hashes the whole model, so a new key changes the hash for every
  historical record too. Fixed with a nullable, un-backfilled column and
  `exclude_none=True` on the hash. Every prior signed-schema change
  (`classification_snapshot` included) landed before any record existed
  under the older shape, so this exact conflict never previously arose.
- **The schema fix that makes a binding's parameters changeable requires
  an application-code fix too.** Relaxing `population_policy_bindings`'
  uniqueness to a partial index scoped to `ACTIVE` (migration `0022`) is
  necessary but not sufficient: `create_population_policy_binding`'s own
  conflict pre-check called `get_by_identity`, which ignores
  `lifecycle_state` and would still reject recreating a deactivated
  binding. Fixed with a new `get_active_by_identity` method, added rather
  than changing `get_by_identity`'s existing, lifecycle-blind semantics,
  which other repositories and `plugins/seed_registry.py` depend on
  unchanged.
- **A genuinely pre-existing, previously-undiscovered defect was found as
  a side effect of this review, not introduced by it**: `policy_bindings`
  (M5) has the identical lifecycle-blind conflict check and the identical
  plain (non-partial) uniqueness constraint `population_policy_bindings`
  had before this fix — meaning `PolicyBinding.severity` has likely never
  actually been changeable via "deactivate and recreate" in this
  platform's history. Deliberately left unfixed inside M8 (M5's scope,
  not the Evaluation Framework) — documented and flagged as a candidate
  for a small, dedicated follow-up.
- **No cross-policy aggregation mechanism.** Each `PopulationPolicy`'s
  finding for a given `(system_id, window)` stays its own independent,
  parallel row, the same "structurally separate, never combined"
  relationship `shadow_findings` has to `findings` — building a
  combining mechanism now, with exactly two policies and no concrete
  requirement to combine their outputs, would be the same premature
  generalization this project has declined at every prior opportunity.

See `docs/milestones/M8.md` for the full design review, hostile-review-
pass corrections, and production-readiness report.

## M7-specific notes

- **"Monitoring" is a minimal, DB-query-backed JSON endpoint, not a
  Prometheus/OpenTelemetry stack.** This platform has one deployment
  environment and no established scraping infrastructure to integrate
  with — introducing real metrics infrastructure now would be designing
  against a deployment topology this project has never had a real case
  for, the same "no second deployment environment" reasoning M5 already
  applied to signing-key custody and M6 applied to a dedicated analytical
  store. See `docs/milestones/M7.md` §13.1 — the highest-stakes call in
  that document.
- **No dashboard, no UI.** "Dashboards" in architecture §9's own citation
  is read as describing what a *future* consumer (M10's Compliance
  Dashboard) renders from M7's metrics, not something M7 itself
  delivers — this platform has never built a UI anywhere in seven
  milestones. See `docs/milestones/M7.md` §13.2.
- **`/readyz` is additive; `/healthz` is byte-for-byte unchanged.**
  Mirrors this project's own standing discipline for an existing,
  already-depended-on endpoint (M2's second ingestion route left the
  first unchanged; M6's population pipeline left both ingestion routes
  unchanged). See `docs/milestones/M7.md` §13.3.
- **Governance-health metrics are windowed (`?since=`, default 24h);
  system-health metrics are not.** An unbounded, all-time count over
  `verdicts`/`findings`/`population_findings` — tables with no retention
  policy, M11 not built — would get slower without limit for as long as
  the platform runs. Found during this milestone's own design-phase
  hostile-review pass, not in the original draft. See
  `docs/milestones/M7.md` §13.15.
- **`evidence_chain`'s size is read via a tail-row `ORDER BY
  sequence_number DESC LIMIT 1`, never `COUNT(*)`.** Postgres has no
  fast, O(1) row count under MVCC; `evidence_chain` is the one table in
  this schema that is permanent and never shrinks, making a `COUNT(*)`
  mistake here the most severe possible instance of it. The response
  field is named `evidence_chain_latest_sequence_number`, not
  `..._length`, specifically so its own name doesn't invite the mistake.
  See `docs/milestones/M7.md` §13.16.
- **Population-binding staleness is a `LEFT JOIN` anchored on `ACTIVE`
  `population_policy_bindings`, never an aggregate starting from
  `population_findings`.** A binding that has never once produced a
  finding — the single most important case this metric exists to catch —
  would otherwise be silently absent from the result instead of showing
  the loudest possible staleness signal (`None`). See
  `docs/milestones/M7.md` §13.17.
- **The readiness check reads a real table (`systems`), not a bare
  `SELECT 1`.** Found during this milestone's own post-implementation
  hostile review: a query touching no table proves connectivity and
  authentication but nothing about whether the running role's actual
  table-level grants are intact — a role that could log in but had every
  grant revoked would still report "reachable." See
  `docs/milestones/M7.md`'s production-readiness review.
- **A bounded database-connection timeout, found necessary while
  implementing the readiness check, not designed in advance.** Connecting
  to a genuinely unreachable host (a silently dropped route, not a fast
  "connection refused") could otherwise hang for the OS's full
  TCP-retransmission timeout — well over a minute, observed directly
  during this milestone's implementation. `db/session.create_db_engine`
  now bounds this for every consumer of the shared engine. See
  `docs/milestones/M7.md`'s production-readiness review.
- **No sandbox-timeout counter — reversed from this milestone's own
  first design draft.** A process-local, in-memory counter would silently
  produce wrong (undercounted, non-additive across replicas) numbers the
  moment this platform runs more than one worker/replica — the one
  metric in this design that would have broken the "computed from
  shared, durable Postgres state, therefore automatically correct under
  horizontal scaling" property every other metric here correctly has.
  `plugins/sandbox.py` remains completely untouched by M7. See
  `docs/milestones/M7.md` §13.11.
- **No authentication was added anywhere, including the two new M7
  endpoints** — consistent with every existing endpoint, but now a
  fourth consecutive milestone (M5, M6, M7) widening a gap every one of
  these reviews has flagged rather than solved. See
  `docs/milestones/M7.md` §13.10.

## M6-specific notes

- **"Async ingestion plane" is read as the async plane population-level
  policies specifically need — not a redesign of the two existing,
  synchronous per-event ingestion routes.** `POST /v1/ingestion/events`
  and `POST /v1/ingestion/events/credit-scorecard` are byte-for-byte
  unchanged: same request/response shape, same synchronous contract. This
  is the single highest-stakes reading call M6 makes — see
  `docs/milestones/M6.md` §13.1 for the full reasoning and the literal
  alternative reading this review declined.
- **The "Event Lake" is a new read pattern, not new storage.** `decision_events`
  (already normalized, already persisted by the unchanged ingestion path)
  is queried in a new, windowed, per-system way by
  `population_engine/window.py` — no new table, no new storage technology.
  See `docs/milestones/M6.md` §13.2.
- **Population-level policies are a new, third plugin port
  (`PopulationPolicy`), never a widened `Policy`.** `Policy.evaluate`'s
  single-event, `Finding`-per-`decision_event_id` contract is structurally
  incompatible with an aggregate result over many decisions — this is not
  a case of two similar things differing slightly, it's two genuinely
  different questions that happen to share the word "policy". See
  `docs/milestones/M6.md` §9/§13.3.
- **Population reads resolve `DIRECT`-ness against the DB-backed
  `protected_attribute_rules` (M5), not the static `classification.py`
  copy `DirectAttributeInInputsPolicy` uses** — the batch job already has
  full database access, so none of the constraints that forced that
  policy onto the static ruleset (M5 §13.9) apply here. See
  `docs/milestones/M6.md` §13.15.
- **A population finding is point-in-time reproducible, not a live view.**
  Because `protected_attribute_rules` is live, admin-mutable data with no
  versioning of its own (unlike `population_policy_version`, which already
  pins the policy's code identity), every `PopulationFinding` embeds
  exactly which classifications it was computed against
  (`classification_snapshot`) — found during this milestone's own
  hostile-review pass, not in the original design draft. `population_findings`
  is append-only at the database-privilege level for the identical reason.
  A "recompute under today's rules" capability is a distinct, deliberately
  unbuilt "what-if" feature. See `docs/milestones/M6.md` §13.16 — this
  review's most consequential correction.
- **Population Policy Bindings are `system_id`-keyed, not `adapter_id`-keyed.**
  A population-level analysis is naturally about a System's aggregate
  decisions across however many adapter versions have produced them over
  time — a new, separate key decision from `policy_bindings`' own
  `adapter_id` key, not a copy-paste of it. See
  `docs/milestones/M6.md` §13.8.
- **Windows are fixed, calendar-aligned, and closed in the past** —
  by default, "yesterday's full UTC day," never `[now() - 30d, now())`.
  Combined with `REPEATABLE READ` window-building reads and a `UNIQUE
  (population_policy_id, system_id, window_start, window_end)` constraint,
  a duplicate or overlapping `run_policies` invocation is a clean,
  detectable no-op, not a race producing two disagreeing findings for
  "the same" window — reversed from this milestone's own first design
  draft during the hostile-review pass. See `docs/milestones/M6.md` §13.13.
- **No authentication was added anywhere, including the two new M6 admin
  endpoints** — consistent with every existing admin endpoint, but
  flagged more sharply than M5's identical gap: `population_findings` is
  the first table in this platform whose entire content is a
  disparate-impact judgment about a real system, not just operational
  config. Named loudly, not solved piecemeal here — see
  `docs/milestones/M6.md` §13.14.

## M5-specific notes

- **Policy Bindings are keyed by `adapter_id`, not `System.domain`/
  jurisdiction — a deliberately narrower reading of "Policy Bindings" than
  the architecture's literal phrase.** The richer, domain/jurisdiction-keyed
  design would require resolving a `DecisionEvent`'s `System.domain`
  *before* `GovernanceEngine` can be constructed, a real ingestion-pipeline
  reorder — deferred until a second real domain exists to design it
  against (`FINANCE` is still the only one). See
  `docs/milestones/M5.md` §13.1 for the full reasoning; this is the single
  highest-stakes call M5 made.
- **Severity lives on `PolicyBinding`, not on `Policy`.** How serious a
  violation is *in the context of a specific adapter* is an administrative
  judgment, not a property of what the policy's code checks — the same
  separation of concerns that already moved `governing_policy_ids` off
  `Adapter` and into the database. `FindingOutcome` stays binary
  `CLEAR`/`FLAGGED`; escalation tier is derived from severity, never stored
  on `Finding`.
- **DB-backed protected-attribute rules apply to `EvidenceStore`'s
  resolution path only — `DirectAttributeInInputsPolicy` deliberately keeps
  reading the static, in-code ruleset.** Unifying both consumers would
  require giving a `Policy` — constructed with zero arguments everywhere in
  this codebase — real database access, a `Policy` port change M5
  intentionally does not make on top of everything else it already
  changes. A named, temporary divergence: an admin editing
  `protected_attribute_rules` changes what gets *persisted* as resolved,
  not what `DirectAttributeInInputsPolicy` *judges* as a leak, until a
  later milestone unifies the two. See `docs/milestones/M5.md` §13.9.
- **Evidence signing is a single static Ed25519 keypair, no KMS/HSM, no
  rotation.** `signing_key_id` travels with every signed record so a
  future rotation milestone can tell which key verifies which record
  without guessing. Real key custody is real infrastructure scope this
  platform has no second deployment environment to design correctly
  against yet — named explicitly, not silently deferred.
- **`VerdictStatus.ALLOW`/`FLAGGED` are permanent, historical-only enum
  members — no data migration of M0–M4 verdicts.** A `Verdict`'s `status`
  is embedded in the hash-chained, immutable `evidence_chain.payload`;
  rewriting the separate, mutable `verdicts.status` column for historical
  rows would make the queryable view disagree with the evidence-of-record
  for the same event. No M5+ code path ever constructs a new
  `GovernanceVerdict` with either legacy value.
- **No authentication was added anywhere, including the two new M5 admin
  endpoints** — consistent with every existing admin endpoint, but flagged
  because Policy Bindings materially raise the stakes of that gap: an
  unauthenticated deactivate call can now silently stop a policy from
  governing real financial decisions. Named loudly in the M5
  production-readiness review, not solved piecemeal here.

## M4-specific notes

- **`governing_policy_ids` is a static, code-defined tuple — not a
  preview of M5's Policy Bindings.** An adapter still declares which
  policy families govern it at class-definition time, the same as M2/M3's
  singular `governing_policy_id`; M4 only widens the type from one string
  to a tuple of strings. Making this database-configurable per-System, at
  runtime, without a redeploy, is exactly the problem M5's Policy Bindings
  exist to solve — M4 deliberately does not reach for it early.
- **Plurality is OR-of-`FLAGGED`, evaluated independently per policy
  family.** `GovernanceEngine.govern` runs every `Policy` in its
  constructor-supplied list and flags the whole `Verdict` if any one of
  them flags — there is no weighting, precedence, or partial-credit
  model, and a policy that raises fails the entire request rather than
  degrading to a partial verdict (`governance_engine/engine.py`'s
  docstring explains why: a silently-dropped Finding is a worse failure
  mode than a loud 500).
- **Shadow execution and policy plurality are orthogonal, by design.**
  A `SHADOW`-state policy for one governing family has zero effect on
  the other families' findings or on the aggregate `Verdict` — each
  family's `PRODUCTION`/`SHADOW` resolution happens independently inside
  the ingestion route, and only `PRODUCTION` policies are ever passed to
  `GovernanceEngine`. See
  `test_shadow_candidate_for_one_family_does_not_affect_the_other_familys_finding`
  in `tests/integration/test_shadow_execution_postgres.py`.
- **The `credit-scorecard` version bump (`0.1.0` → `0.2.0`) is the
  worked example of the M3 lifecycle mechanism doing real work, not just
  passing tests.** Registering `0.2.0` as `PRODUCTION` auto-demotes
  `0.1.0` to `SHADOW` via the database's partial unique index — verified
  live against the real containerized Postgres (not just the test suite)
  by seeding the registry and querying `plugin_registrations` directly.
  The version bump itself follows the same rule M3 established: a
  behavior change to what a versioned plugin identity means is a new
  version registered through the lifecycle, never a silent mutation of
  what `0.1.0` meant while it was `PRODUCTION`.

## M3-specific notes

- **Route existence vs. route behavior — two different DB-dependency
  rules, deliberately.** `api/ingestion/routes.py`'s
  `build_ingestion_router()` generates routes from the **in-process**
  plugin registry only (`plugins.bootstrap`'s imports) — zero database
  access, preserving the invariant every milestone since M0 has relied on
  (`create_app()` needs no live database). Which policy actually governs
  a given request (`PRODUCTION` vs `SHADOW`) is resolved **fresh from the
  database on every request**, inside the generated handler — so
  promoting/demoting a plugin via the Admin API takes effect on the very
  next request, no restart needed. Don't conflate the two: a route can
  exist and still reject traffic with a `503` if its adapter or policy
  isn't actually `PRODUCTION` yet.
- **A never-registered adapter and an explicit `DRAFT` registration are
  rejected identically.** Both mean "not accepting production traffic
  yet" from the caller's perspective — a `503`, not a `404` (the route
  itself genuinely exists; it's just not live).
- **Adapter-level `SHADOW` has no distinct meaning from `PRODUCTION` yet.**
  Both fully process and persist real traffic identically. The
  meaningful `SHADOW` distinction M3 actually delivers is for
  **policies** — evaluated against real traffic, persisted to
  `shadow_findings`, never affecting the served Verdict. Extending
  shadow semantics to adapters (e.g., processing real traffic without
  committing evidence) is a reasonable future enhancement, not built now.
- **Sandboxing is a soft timeout + exception isolation, not process/
  container isolation** — a deliberate scope decision (see
  `docs/milestones/M3.md` §13.1), because there is no untrusted
  third-party plugin author yet. A plugin that hangs forever still
  consumes a background thread forever; the caller just stops waiting
  for it. Read `plugins/sandbox.py`'s docstring before assuming this
  provides security isolation — it does not.
- **`create`/`promote` on the plugin registry translate a real database
  race into a clean `ValueError`, but not symmetrically with the Admin
  API's own pre-checks** — see `docs/milestones/M3.md`'s production-
  readiness review for the accepted `409` vs `422` inconsistency this
  leaves, and why the `promote()` race specifically has no direct test
  (a genuine two-thread test was attempted and found to assert a false
  invariant under low contention).

## M2-specific notes

- **Two adapters, two ingestion routes, one shared ledger.** `SyntheticAdapter`
  and `CreditScorecardAdapter` each have their own route and their own,
  independently-policied `GovernanceEngine` — but both write into the same
  `EvidenceStore`, one append-only chain platform-wide. Real adapter
  registry/dispatch by `system_id` behind a single endpoint remains M3.
- **`ProtectedAttributeResolver` is scoped to one domain (`FINANCE`).**
  `DirectAttributeInInputsPolicy` is fixed to that domain at construction
  time (it has no database access, so it cannot look up `System.domain`
  dynamically); `EvidenceStore`'s own resolution, by contrast, uses whatever
  domain the ingesting `System` is actually registered with, which defaults
  to `None` (nothing resolved/persisted) unless pre-registered via the
  Admin API with `domain="FINANCE"`. The policy's judgment and what gets
  persisted to `protected_attribute_resolutions` can therefore diverge for
  an auto-provisioned (never explicitly registered) credit-scorecard
  system — a known, documented consequence of auto-provisioning, not a bug.
- **An unrecognized protected attribute is a hard failure, not a silent
  default.** `ProtectedAttributeResolver.resolve` raises `ValueError` if a
  known domain (`FINANCE`) receives an attribute name its ruleset doesn't
  recognize — surfaced to API clients as `422`, not `500`, via a dedicated
  `ValueError` exception handler in `api/app.py` (a production-readiness
  finding fixed before freeze — see `docs/milestones/M2.md`).

## M1-specific notes

- **Auto-provisioning, not enforcement.** `EvidenceStore.append` auto-
  provisions a System/ModelVersion by name if one doesn't already exist,
  rather than requiring pre-registration. This keeps M0's ingestion route
  byte-for-byte unchanged. Strict validation/authorization of which systems
  may ingest is a later-milestone concern (M3 adapter registry, M5 policy
  bindings), not something M1 introduces early.
- **`decision_events.id` is now a real primary key.** A deliberate new
  constraint M0's single blob table never enforced — see
  `db/repositories/decision_event.py`.
- **Local testability.** Everything DB-agnostic (the hash-chain algorithm,
  `verify_chain`'s core logic, the migration runner's discovery/ordering/
  idempotency mechanism) is unit-tested with no Postgres involved. Anything
  that needs a real schema or real privilege enforcement is `@requires_postgres`
  and runs in CI only — see `docs/milestones/M1.md` for why this sandbox
  can't run Postgres itself.
