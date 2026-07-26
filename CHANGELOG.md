# Changelog

All notable changes to this project are documented in this file. Entries are
grouped by milestone (`ARCH-GOV-002` / `IMPL-GOV-001`), not by release date,
since this project ships as a sequence of frozen, incremental milestones
rather than continuous releases.

## [0.2.0-m1] — 2026-07-26 — M1: Postgres Persistence & System Registry

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
