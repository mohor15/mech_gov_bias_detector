# Architecture → Module Mapping (M4)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M4 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + two implementations. `CreditScorecardAdapter` is `0.2.0` as of M4 — `governing_policy_ids` widened to a tuple (below). Ingestion routes are still generated from whichever adapters are registered (`api/ingestion/routes.py`), not hand-written per adapter. |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M4. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py` | Classifies each of a domain's expected protected attributes as `DIRECT`/`PROXIED`/`WITHHELD` (a concrete service, not a plugin port). Rules are static code, scoped to one domain (`FINANCE`); DB-backed, admin-configurable rules remain M5 — unchanged by M4. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py`, `plugins/registry.py`, `plugins/bootstrap.py`, `plugins/sandbox.py`, `schemas/plugin_registration.py`, `db/repositories/plugin_registration.py`, `api/admin/plugins.py` | In-process registry + database-backed lifecycle state + a timeout/exception-isolation sandbox around every plugin call — unchanged mechanism, exercised by M4 for a real version transition (`credit-scorecard` `0.1.0` → `0.2.0`, verified to auto-demote correctly). `Adapter`/`Policy` remain the only two ports. |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/always_allow.py`, `policy_engine/policies/direct_attribute_in_inputs.py`, `policy_engine/policies/high_debt_ratio_gate.py` | Real port + **three** reference policies as of M4. `Policy.evaluate(event) -> Finding`'s signature remains unchanged — plurality is orchestrated by `GovernanceEngine` collecting multiple `Policy` instances, not by widening what each one receives. Population-level policies remain M6/M8. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | **M4: real policy plurality.** `GovernanceEngine(policies: list[Policy])` runs every policy and aggregates via any-`FLAGGED`-wins; `findings` can now genuinely hold more than one entry. A `SHADOW`-state policy's Finding is still evaluated and persisted to `shadow_findings` by the ingestion route directly, per policy family, independent of how many families an adapter declares — it never reaches this class or the served Verdict. Policy Bindings, the full four-state model, escalation, and signing remain M5. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | *(not yet built)* | M8. |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py` | Real hash-chained Postgres ledger, append-only enforced at the database-privilege level, plus a standalone chain-verification job/CLI. Unchanged by M3 — `shadow_findings` is a deliberately separate table, never touching the evidence chain. Retention tiers and privilege classification remain M11. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/admin/plugins.py`, `api/app.py`, `api/asgi.py` | Ingestion routes are registry-generated (one per registered adapter — currently `synthetic` and `credit-scorecard`, same URL scheme as M2 but no longer hand-written). **New in M3**: the Plugin Registry Admin API (`register`/`list`/`get`/`promote`), alongside System registration (M1). Advisory, Config (beyond System/Plugins), Query/Reporting, and Webhook APIs arrive with the milestones that give them something to expose. `app.py` is the side-effect-free factory; `asgi.py` is the only module that actually constructs the default instance. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py`, `schemas/plugin_registration.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity, now including **`PluginRegistration` and shadow-Finding persistence, new in M3** (migration `0010`). SQLAlchemy models are query-time mappings only — never used to generate DDL, so there is exactly one source of schema truth. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres. Multi-plane topology, multi-tenancy, and mTLS are M13. |

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
