# Architecture → Module Mapping (M0)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise M0 boundary — what's real today vs. what's deferred and to
which milestone. Read alongside each module's own docstring, which is the
authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | M0 status |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py` | Real port + one reference adapter. Registry/discovery for multiple adapters is M3. |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision). |
| §4.3 Protected Attribute Resolution Service | *(not yet built)* | `DecisionEvent.protected_attribute_refs` carries raw adapter-supplied values, unresolved. Direct/proxied/withheld resolution is M2. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py` | The two ports exist. Sandboxing, discovery, and draft/shadow/production promotion states are M3. |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/always_allow.py` | Real port + one reference policy. Policy plurality and disagreement surfacing are M4; population-level policies are M6/M8. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Wraps exactly one Policy's Finding into a Verdict. Bindings, the full four-state model, escalation, and signing are M5. |
| §9 Monitoring | `observability/logging.py` | Structured logging only. System/governance-health metrics and dashboards are M7 — hence the separate, narrower `observability` package rather than `monitoring`. |
| §10 Evaluation Framework | *(not yet built)* | M8. |
| §11 Compliance Dashboard | *(not yet built)* | M10. |
| §12 Human Review Workflow | *(not yet built)* | M9. |
| §13 Audit System | `audit/evidence_store.py` | Real hash-chained SQLite ledger; append-only enforced at the application layer. Postgres, DB-privilege enforcement, retention tiers, and privilege classification are M1/M11. |
| §14 Reporting | *(not yet built)* | M12. |
| §15 APIs | `api/health.py`, `api/ingestion/routes.py`, `api/app.py`, `api/asgi.py` | Ingestion API only. Advisory, Admin/Config, Query/Reporting, and Webhook APIs arrive with the milestones that give them something to expose. `app.py` is the side-effect-free factory; `asgi.py` is the only module that actually constructs the default instance, deliberately kept separate — see its docstring. |
| §16 Database Design | `audit/evidence_store.py` (SQLAlchemy ORM) | SQLite today. The repository-style access pattern is chosen so the M1 move to Postgres changes a connection string and adds GRANT/REVOKE, not the calling code. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service. Multi-plane topology, multi-tenancy, and mTLS are M13. |
