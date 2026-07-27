# Changelog

All notable changes to this project are documented in this file. Entries are
grouped by milestone (`ARCH-GOV-002` / `IMPL-GOV-001`), not by release date,
since this project ships as a sequence of frozen, incremental milestones
rather than continuous releases.

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
