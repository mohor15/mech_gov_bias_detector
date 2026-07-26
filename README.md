# AI Governance Platform — M1: Postgres Persistence & System Registry

A domain-agnostic observation-and-evaluation layer for LLM copilots, classical
ML models, rule engines, and hybrid decision systems. This repository
implements the frozen V2 architecture (`ARCH-GOV-002`) incrementally, per the
frozen implementation plan (`IMPL-GOV-001`).

**Current milestone: M1.** Replaces M0's SQLite placeholder with a real
Postgres operational store and hash-chained evidence ledger, formalizes
System/ModelVersion entities, and enforces evidence append-only-ness at the
database-privilege level, not just in application code. See
[`docs/architecture-mapping.md`](docs/architecture-mapping.md) for exactly
what each module does and does not yet do, and
[`docs/milestones/M1.md`](docs/milestones/M1.md) for the full milestone
report.

> **Do not point this milestone at real applicant/subject data.** The
> Evidence Store has no encryption at rest and no retention controls yet
> (M11), and there is still no auth in front of any endpoint (M5+/M13).
> Synthetic data only.

> **This sandbox has no local Postgres.** M1's persistence layer,
> migrations, and DB-privilege enforcement are verified in CI (a real
> Postgres service container), not in this development environment — see
> "Testing" below and `docs/milestones/M1.md` for what that means in
> practice.

Version 1 (a single-domain prototype, superseded by this design) is preserved,
unmodified, in [`legacy_v1/`](legacy_v1/) for reference.

## Requirements

- Python 3.11+
- A real Postgres instance (15+) for anything beyond lint/type-check/the
  DB-independent half of the test suite — see "Testing"
- Docker + Docker Compose, for the containerized run path

## Run locally

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash; use venv/bin/activate on Linux/macOS
pip install -e ".[dev]"
# Reproducible install instead: pip install -r requirements-lock.txt && pip install -e . --no-deps
```

Apply migrations (needs an admin/owner-privileged connection — see
`infra/migrations/0008_grant_evidence_chain_privileges.sql` for why the
app's own runtime role is deliberately not privileged enough to do this):

```bash
python -m gov_platform.db.migrate --database-url "postgresql://postgres:<password>@localhost:5432/gov_platform"
```

Then enable the restricted application role migration `0008` creates
(NOLOGIN by design — see that migration's comments) with a real,
secret-managed password, and point the app at it:

```bash
export GOV_PLATFORM_DATABASE_URL="postgresql+psycopg://gov_platform_app:<password>@localhost:5432/gov_platform"
uvicorn gov_platform.api.asgi:app --reload
```

Then:

```bash
curl http://127.0.0.1:8000/healthz
# {"status":"HEALTHY"}

curl -X POST http://127.0.0.1:8000/v1/admin/systems \
  -H "Content-Type: application/json" \
  -d '{"name": "synthetic-scorecard", "domain": "FINANCE"}'

curl -X POST http://127.0.0.1:8000/v1/ingestion/events \
  -H "Content-Type: application/json" \
  -d '{
        "source_event_id": "evt-001",
        "source_system": "synthetic-scorecard",
        "decision_type": "credit_decision",
        "subject_reference": "subject-001",
        "occurred_at": "2026-01-01T00:00:00Z",
        "features": {"annual_income": 65000.12},
        "protected_attributes": {"country": "India"},
        "decision": {"approved": true, "rate": 0.085}
      }'
```

Registering the system first is optional — ingestion auto-provisions an
unregistered `system_id` by name (see `EvidenceStore`'s module docstring for
why). Pre-registering gets you the richer `domain`/`risk_tier`/`owner`
metadata attached instead of a bare name.

Verify the evidence hash chain independently at any time:

```bash
python -m gov_platform.audit.verify_chain --database-url "$GOV_PLATFORM_DATABASE_URL"
```

## Run with Docker

```bash
docker compose -f infra/docker/docker-compose.yml up --build
```

Note: the compose file runs the app container only — it does not provision a
Postgres instance. Point `GOV_PLATFORM_DATABASE_URL` at one you already have
running (a real docker-compose-managed Postgres service is a reasonable local
convenience to add, but doing that now would be ahead of what M1 actually
needs to demonstrate — a real question for whoever sets up local-dev tooling
next, not implied by anything M1 committed to).

## Testing

```bash
ruff check src tests      # lint
mypy src                  # type-check (strict, src/ only)
pytest                    # runs everything that doesn't need Postgres; DB-dependent tests skip cleanly
```

Tests that need a live database (the repository layer, `EvidenceStore`'s
behavioral tests, the Admin API, and — critically — the DB-privilege
enforcement test) are marked `@requires_postgres` and skip with a clear
reason when `POSTGRES_URL` isn't set. To run the full suite locally against
your own Postgres:

```bash
python -m gov_platform.db.migrate --database-url "postgresql://postgres:<password>@localhost:5432/gov_platform"
# then, as the postgres superuser or equivalent:
#   ALTER ROLE gov_platform_app WITH LOGIN PASSWORD '<password>';
export POSTGRES_URL="postgresql+psycopg://gov_platform_app:<password>@localhost:5432/gov_platform"
pytest --cov-fail-under=98   # the coverage floor only means something with POSTGRES_URL set
```

CI always sets `POSTGRES_URL` (a real Postgres 16 service container) and
enforces the coverage floor there — see `.github/workflows/ci.yml`.

## Development commands

```bash
pre-commit install        # optional: run ruff + mypy on every commit
```

## Repository layout

```
src/gov_platform/
  config/              Settings (env-driven)
  observability/       Structured (JSON) logging
  schemas/             Canonical DecisionEvent, Finding, GovernanceVerdict, System, ModelVersion
  adapters/            Adapter[TPayload] port + SyntheticAdapter (reference impl)
  normalization/       Structural normalization pass
  policy_engine/       Policy port + AlwaysAllowPolicy (reference impl)
  governance_engine/   Wraps a Policy's Finding into a Verdict
  audit/               hash_chain.py (pure), evidence_store.py (Postgres), verify_chain.py
  db/                  session.py, migrate.py, models.py, repositories/
  api/
    app.py             Composition root
    asgi.py            The only module that constructs the default instance
    dependencies.py    DI providers, typed against ports where ports exist
    middleware.py      MaxBodySizeMiddleware
    health.py          GET /healthz
    ingestion/         POST /v1/ingestion/events
    admin/             POST/GET /v1/admin/systems
infra/
  docker/              Dockerfile, docker-compose.yml
  migrations/          Numbered, Postgres-targeting .sql files
  ci/                  CI-only helper scripts (never used by the app itself)
tests/unit/            One test module per src module; DB-independent
tests/integration/     Full HTTP/DB round-trip tests; most need @requires_postgres
legacy_v1/             Superseded V1 prototype (reference only, not run)
```

## What M1 deliberately does not include

Every module has a docstring stating precisely which milestone owns the
capability it doesn't yet have. The short version: Protected Attribute
Resolution and a real (non-synthetic) adapter (M2), plugin
registry/discovery/sandboxing (M3), policy plurality (M4), the full
four-state verdict model with bindings/escalation/signing (M5), async
ingestion and population-level policies (M6), encryption at rest and
retention (M11), and comprehensive request-abuse protection beyond the
`Content-Length` check added during M0's finalization (M13). Building any of
that now would violate the milestone's own scope.

## What remains for M2

See [`docs/milestones/M1.md`](docs/milestones/M1.md) for the full deferred-
items table with milestone ownership. In short: M2 formalizes Protected
Attribute Resolution (direct/proxied/withheld) and ships the first real
(non-synthetic) adapter and the first genuinely judgment-bearing policy.
