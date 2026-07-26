# Architecture → Module Mapping (M1)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M1 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py` | Real, generic (`Adapter[TPayload]`) port + one reference adapter. Registry/discovery for multiple adapters is M3. |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision). |
| §4.3 Protected Attribute Resolution Service | *(not yet built)* | `DecisionEvent.protected_attribute_refs` carries raw adapter-supplied values, unresolved. Direct/proxied/withheld resolution is M2. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py` | The two ports exist. Sandboxing, discovery, and draft/shadow/production promotion states are M3. |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/always_allow.py` | Real port + one reference policy. Policy plurality and disagreement surfacing are M4; population-level policies are M6/M8. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Wraps exactly one Policy's Finding into a Verdict. Bindings, the full four-state model, escalation, and signing are M5. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | *(not yet built)* | M8. |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py` | **M1: real hash-chained Postgres ledger, append-only enforced at the database-privilege level** (`infra/migrations/0008_...`), plus a standalone chain-verification job/CLI. Concurrency uses `pg_advisory_xact_lock`, replacing M0's in-process lock — correct across multiple app instances, not just within one process. Retention tiers and privilege classification remain M11. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/app.py`, `api/asgi.py` | Ingestion API (unchanged from M0) + **Admin API for System registration, new in M1**. Advisory, Config (beyond System), Query/Reporting, and Webhook APIs arrive with the milestones that give them something to expose. `app.py` is the side-effect-free factory; `asgi.py` is the only module that actually constructs the default instance. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py` | **M1: real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity** (System, ModelVersion, DecisionEvent, Finding, Verdict). SQLAlchemy models are query-time mappings only — never used to generate DDL, so there is exactly one source of schema truth. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres. Multi-plane topology, multi-tenancy, and mTLS are M13. |

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
