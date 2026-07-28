# Architecture → Module Mapping (M6)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M6 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + two implementations. **Unchanged by M6** — both ingestion routes, and everything downstream of them, are byte-for-byte identical to M5 (see M6-specific notes: the async plane M6 builds is additive and parallel, not a change to per-event ingestion). |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M6. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py`, `schemas/protected_attribute_rule.py`, `db/repositories/protected_attribute_rule.py` | Unchanged by M6 for this service itself. **M6 adds a third, read-only consumer** of the DB-backed `protected_attribute_rules` table (`population_engine/window.py`, via its own direct repository call, not through `ProtectedAttributeResolver`) — see M6-specific notes on why, and on the reproducibility consequence that creates. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py`, `population_engine/base.py`, `plugins/registry.py`, `plugins/bootstrap.py`, `plugins/sandbox.py`, `schemas/plugin_registration.py`, `db/repositories/plugin_registration.py`, `api/admin/plugins.py` | In-process registry + database-backed lifecycle state + a timeout/exception-isolation sandbox around every plugin call. **New in M6**: `PluginType.POPULATION_POLICY` — a third plugin kind, using the exact same registry/lifecycle mechanism `Adapter`/`Policy` already do, no second mechanism invented. `Adapter`/`Policy`/`PopulationPolicy` are now the three ports; Policy Bindings and Population Policy Bindings are separate, orthogonal axes (*which* trusted policies apply, not *whether* a policy's code is trusted). |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/*.py`, `schemas/policy_binding.py`, `db/repositories/policy_binding.py`, `api/admin/policy_bindings.py` | Real port + three reference policies, unchanged by M6. `Policy.evaluate(event) -> Finding`'s signature remains untouched — population-level evaluation is a deliberately separate, parallel port (`population_engine/base.py`, below), never a widened `Policy`. |
| §7/§8 Population-Level Policy Engine | `population_engine/base.py` (`PopulationPolicy`, `PopulationWindow`, `PopulationGroupCount`), `population_engine/window.py`, `population_engine/policies/adverse_impact_ratio.py`, `population_engine/run_policies.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py`, `db/repositories/population_finding.py`, `db/repositories/population_policy_binding.py`, `api/admin/population_findings.py`, `api/admin/population_policy_bindings.py` | **New in M6.** A third plugin port, `PopulationPolicy`, evaluating many `DecisionEvent`s for one `System` over one time window into one `PopulationFinding` — structurally parallel to, and never touching, `Policy`/`Finding`/`Verdict`. One concrete policy ships: `adverse-impact-ratio` (EEOC "4/5ths rule", 29 CFR § 1607.4(D)). Triggered by an explicitly-invoked batch CLI (`population_engine/run_policies.py`), not a daemon or in-process scheduler — this *is* "the async ingestion plane" (§4.1's citation), read as the plane population-level policies specifically need, not a redesign of per-event ingestion. `PopulationPolicyBinding` is `system_id`-keyed, a new table, deliberately separate from `policy_bindings`. See M6-specific notes. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Unchanged by M6. `GovernanceEngine`/`GovernanceVerdict` remain per-event; population-level results never flow through them. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | `population_engine/policies/adverse_impact_ratio.py` (one concrete metric only) | **Partially real as of M6** — one hardcoded population-level metric, not a general, pluggable statistical-evaluation framework. A configurable-metric framework (multiple tests, admin-defined thresholds) remains M8's job; M6 deliberately does not reach for it early (see `docs/milestones/M6.md` §13.9). |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9 — an `ESCALATE_FOR_REVIEW` verdict (M5) and a `FLAGGED` `PopulationFinding` (M6) are both fully computed and persisted; nothing yet queues either for a human to act on. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py`, `audit/signing.py`, `audit/verify_population_findings.py` | Real hash-chained Postgres ledger for per-event evidence, append-only enforced at the database-privilege level, plus a standalone chain-verification job/CLI — unchanged by M6. **New in M6**: `population_findings` gets the identical append-only privilege lockdown (`REVOKE UPDATE, DELETE`, migration `0015`) and is signed (reusing `audit/signing.py` unchanged) — but is **not chained** into `evidence_chain` (no `previous_hash`, no single `decision_event_id` it belongs to). `audit/verify_population_findings.py` is a separate, parallel verifier — a plain content hash over each finding's own canonical payload (including `classification_snapshot`), not `hash_chain`'s chained variant. Key rotation/KMS custody and retention tiers remain unassigned/M11 for both. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/admin/plugins.py`, `api/admin/policy_bindings.py`, `api/admin/protected_attribute_rules.py`, `api/admin/population_policy_bindings.py`, `api/admin/population_findings.py`, `api/app.py`, `api/asgi.py` | Ingestion routes are registry-generated (one per registered adapter — currently `synthetic` and `credit-scorecard`), **unchanged by M6**, same response shape. **New in M6**: the Population Policy Bindings Admin API (`create`/`list`/`get`/`activate`/`deactivate`, `system_id`-keyed) and the Population Findings Admin API (`list`/`get` only, optionally filtered by `system_id` — no `POST`; a finding is only ever produced by the batch CLI). No endpoint anywhere has authentication yet, including these two — the same standing gap M5 named, flagged more sharply here since a population finding's entire content is a disparate-impact judgment about a real system (see M6-specific notes). `app.py` is still the side-effect-free factory; the batch CLI is never wired into it. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py`, `schemas/plugin_registration.py`, `schemas/policy_binding.py`, `schemas/protected_attribute_rule.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity. **New in M6**: `population_policy_bindings` (ordinary privileges, migration `0014`) and `population_findings` (append-only, migration `0015`) tables, plus an index on `decision_events(model_version_id, occurred_at)` (migration `0016`) supporting the one new windowed-read pattern this milestone introduces. No existing table altered. SQLAlchemy models are query-time mappings only — never used to generate DDL. Multi-tenancy and the analytical-warehouse split (the long-term answer to the "Event Lake" if real query volume ever demands one — see M6-specific notes) remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres — unchanged by M6. The batch CLI runs as a separate process against the same database, not a second service definition; real scheduling of it (cron, a Kubernetes `CronJob`) is deployment topology, M13-adjacent, not built. Multi-plane topology, multi-tenancy, and mTLS are M13. |

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
