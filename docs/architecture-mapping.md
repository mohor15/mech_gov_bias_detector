# Architecture → Module Mapping (M5)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M5 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + two implementations. `governing_policy_ids` is **removed** as of M5 — which policies govern an adapter is now a `policy_bindings` database fact (§7/§8 below), not a class attribute. Ingestion routes are still generated from whichever adapters are registered (`api/ingestion/routes.py`), not hand-written per adapter. |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M5. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py`, `schemas/protected_attribute_rule.py`, `db/repositories/protected_attribute_rule.py` | **M5: DB-backed for one consumer.** `ProtectedAttributeResolver` now supports two ruleset sources, chosen once at construction: the static, in-code `classification.py` rules by default (unchanged — still what `DirectAttributeInInputsPolicy` uses), or the admin-configurable `protected_attribute_rules` table when constructed with an `Engine` (what `EvidenceStore` uses). A deliberate, named divergence between the two consumers — see M5-specific notes below. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py`, `plugins/registry.py`, `plugins/bootstrap.py`, `plugins/sandbox.py`, `schemas/plugin_registration.py`, `db/repositories/plugin_registration.py`, `api/admin/plugins.py` | In-process registry + database-backed lifecycle state + a timeout/exception-isolation sandbox around every plugin call — unchanged by M5. `Adapter`/`Policy` remain the only two ports; Policy Bindings (below) are a separate, orthogonal axis (*which* trusted policies apply, not *whether* a policy's code is trusted). |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/*.py`, `schemas/policy_binding.py`, `db/repositories/policy_binding.py`, `api/admin/policy_bindings.py` | Real port + three reference policies, unchanged by M5. **New in M5**: Policy Bindings — a `policy_bindings` table, keyed by `adapter_id` (not domain/jurisdiction — see M5-specific notes), admin-managed via `api/admin/policy_bindings.py`, carrying each binding's `PolicySeverity`. `Policy.evaluate(event) -> Finding`'s signature remains unchanged. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | **M5: real escalation.** `GovernanceEngine(governing_policies: list[GoverningPolicy])` runs every policy and aggregates via highest-flagged-severity-wins into the full four-state `VerdictStatus` (`ALLOW` / `ALLOW_WITH_FLAG` / `ESCALATE_FOR_REVIEW` / `RECOMMEND_HOLD`), replacing M0–M4's two-state placeholder. `FLAGGED` remains a permanent, historical-only enum member for pre-M5 rows. A `SHADOW`-state policy's Finding is still evaluated and persisted to `shadow_findings` independently — unaffected by escalation. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | *(not yet built)* | M8. |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9 — an `ESCALATE_FOR_REVIEW` verdict is fully computed and persisted by M5; nothing yet queues it for a human to act on. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py`, `audit/signing.py` | Real hash-chained Postgres ledger, append-only enforced at the database-privilege level, plus a standalone chain-verification job/CLI. **New in M5**: every evidence record is signed (Ed25519, single static key — see M5-specific notes) at write time; `verify_chain`/its CLI optionally verify signatures too, given a public key. `shadow_findings` remains a deliberately separate table, never touching the evidence chain. Key rotation/KMS custody and retention tiers remain unassigned/M11. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/admin/plugins.py`, `api/admin/policy_bindings.py`, `api/admin/protected_attribute_rules.py`, `api/app.py`, `api/asgi.py` | Ingestion routes are registry-generated (one per registered adapter — currently `synthetic` and `credit-scorecard`). **New in M5**: the Policy Bindings Admin API (`create`/`list`/`get`/`activate`/`deactivate`) and the Protected Attribute Rules Admin API (`create`/`list`/`get`, no lifecycle). Neither loads new code — both manage facts about already-deployed `Adapter`/`Policy` implementations. No endpoint anywhere has authentication yet, including these two — a deliberate, explicitly-named M5 non-goal (see M5-specific notes). `app.py` is the side-effect-free factory; `asgi.py` is the only module that actually constructs the default instance. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py`, `schemas/plugin_registration.py`, `schemas/policy_binding.py`, `schemas/protected_attribute_rule.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity. **New in M5**: `policy_bindings` and `protected_attribute_rules` tables (migrations `0011`/`0012`), plus nullable `signature`/`signing_key_id` columns on `evidence_chain` (migration `0013`). SQLAlchemy models are query-time mappings only — never used to generate DDL. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres. Multi-plane topology, multi-tenancy, and mTLS are M13. |

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
