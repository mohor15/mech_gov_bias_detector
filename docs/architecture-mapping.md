# Architecture → Module Mapping (M2)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M2 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + **two** implementations as of M2 (`SyntheticAdapter`, `CreditScorecardAdapter`), each behind its own ingestion route. Registry/discovery so one endpoint can dispatch by `system_id` is still M3. |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M2. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py` | **M2: real.** Classifies each of a domain's expected protected attributes as `DIRECT`/`PROXIED`/`WITHHELD` (a concrete service, not a plugin port — see `docs/milestones/M2.md` §7). Rules are static code, scoped to one domain (`FINANCE`); DB-backed, admin-configurable rules remain a named future item (M3/M5). |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py` | The two ports exist, unchanged by M2 (`ProtectedAttributeResolver` is deliberately not a third one). Sandboxing, discovery, and draft/shadow/production promotion states are M3. |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/always_allow.py`, `policy_engine/policies/direct_attribute_in_inputs.py` | Real port + **two** reference policies as of M2. `DirectAttributeInInputsPolicy` is the first that can actually produce `FLAGGED`, and the first with a constructor dependency (`ProtectedAttributeResolver`) — `Policy.evaluate(event) -> Finding`'s signature is unchanged. Policy plurality and disagreement surfacing are M4; population-level policies are M6/M8. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Wraps exactly one Policy's Finding into a Verdict. Bindings, the full four-state model, escalation, and signing are M5. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | *(not yet built)* | M8. |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py` | **M1: real hash-chained Postgres ledger, append-only enforced at the database-privilege level** (`infra/migrations/0008_...`), plus a standalone chain-verification job/CLI. Concurrency uses `pg_advisory_xact_lock`, replacing M0's in-process lock — correct across multiple app instances, not just within one process. Retention tiers and privilege classification remain M11. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/app.py`, `api/asgi.py` | Ingestion API now has **two routes** (`/v1/ingestion/events`, `/v1/ingestion/events/credit-scorecard` — new in M2, one per adapter) + Admin API for System registration (M1). Advisory, Config (beyond System), Query/Reporting, and Webhook APIs arrive with the milestones that give them something to expose. `app.py` is the side-effect-free factory; `asgi.py` is the only module that actually constructs the default instance. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity (System, ModelVersion, DecisionEvent, Finding, Verdict, and **ProtectedAttributeResolution, new in M2**). SQLAlchemy models are query-time mappings only — never used to generate DDL, so there is exactly one source of schema truth. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres. Multi-plane topology, multi-tenancy, and mTLS are M13. |

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
