# Changelog

All notable changes to this project are documented in this file. Entries are
grouped by milestone (`ARCH-GOV-002` / `IMPL-GOV-001`), not by release date,
since this project ships as a sequence of frozen, incremental milestones
rather than continuous releases.

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
