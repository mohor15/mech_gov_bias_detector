# AI Governance Platform — M3: Plugin Registry, Lifecycle & Sandboxing

A domain-agnostic observation-and-evaluation layer for LLM copilots, classical
ML models, rule engines, and hybrid decision systems. This repository
implements the frozen V2 architecture (`ARCH-GOV-002`) incrementally, per the
frozen implementation plan (`IMPL-GOV-001`).

**Current milestone: M3.** Replaces M2's two hand-wired adapter/policy pairs
with a real plugin registry: adapters and policies are registered with a
`draft`/`shadow`/`production` lifecycle, ingestion routes are generated from
whatever is registered (not hand-written per adapter), and every plugin call
runs under a timeout + exception-isolating sandbox. See
[`docs/architecture-mapping.md`](docs/architecture-mapping.md) for exactly
what each module does and does not yet do, and
[`docs/milestones/M3.md`](docs/milestones/M3.md) for the full milestone
report.

> **Do not point this milestone at real applicant/subject data.** The
> Evidence Store (and `protected_attribute_resolutions`) has no encryption
> at rest and no retention controls yet (M11), and there is still no auth in
> front of any endpoint (M5+/M13). Synthetic data only.

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
secret-managed password:

```bash
export GOV_PLATFORM_DATABASE_URL="postgresql+psycopg://gov_platform_app:<password>@localhost:5432/gov_platform"
```

**New in M3, and required before ingestion will accept anything**: seed the
plugin registry. Ingestion routes are generated from whichever adapters
this process's code has registered (`plugins/bootstrap.py`), but each one
rejects real traffic until its lifecycle state reaches `PRODUCTION` — a
fresh database has no plugin registrations at all yet, the same way it has
no migrations applied until you run them:

```bash
python -m gov_platform.plugins.seed_registry --database-url "$GOV_PLATFORM_DATABASE_URL"
# ADAPTER synthetic 0.1.0: promoted to PRODUCTION
# ADAPTER credit-scorecard 0.1.0: promoted to PRODUCTION
# POLICY always-allow 0.1.0: promoted to PRODUCTION
# POLICY direct-attribute-in-inputs 0.1.0: promoted to PRODUCTION
```

Now start the app:

```bash
uvicorn gov_platform.api.asgi:app --reload
```

Then:

```bash
curl http://127.0.0.1:8000/healthz
# {"status":"HEALTHY"}

curl -X POST http://127.0.0.1:8000/v1/admin/systems \
  -H "Content-Type: application/json" \
  -d '{"name": "synthetic-scorecard", "domain": "FINANCE"}'

curl -X POST http://127.0.0.1:8000/v1/ingestion/events/synthetic \
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

**The credit scorecard route** — a realistic classical-ML adapter, governed
by a policy that actually flags a protected attribute leaking into the
model's own inputs. Pre-registering the system with `domain: "FINANCE"`
is what makes `protected_attribute_resolutions` persist anything for
it — see `docs/milestones/M2.md`'s production-readiness review for why:

```bash
curl -X POST http://127.0.0.1:8000/v1/admin/systems \
  -H "Content-Type: application/json" \
  -d '{"name": "credit-scorecard-prod", "domain": "FINANCE"}'

curl -X POST http://127.0.0.1:8000/v1/ingestion/events/credit-scorecard \
  -H "Content-Type: application/json" \
  -d '{
        "decision_id": "score-001",
        "applicant_id": "applicant-001",
        "system_name": "credit-scorecard-prod",
        "scored_at": "2026-01-01T00:00:00Z",
        "feature_vector": {"annual_income": 65000.12, "debt_to_income": 0.31},
        "demographic_indicators": {"race": "Black", "zip_code": "12345"},
        "model_score": 712.5,
        "decision_threshold": 650.0,
        "approved": true,
        "reason_codes": ["R01"]
      }'
# status: "ALLOW" -- protected attributes stayed out of feature_vector.
# Move "race" into feature_vector instead and this becomes "FLAGGED".
```

**Managing the plugin registry** — list what's registered, or promote a
`DRAFT`/`SHADOW` candidate one lifecycle stage:

```bash
curl http://127.0.0.1:8000/v1/admin/plugins

curl -X POST http://127.0.0.1:8000/v1/admin/plugins/<registration-id>/promote
```

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

You do **not** need to run `plugins.seed_registry` separately before
`pytest`: a session-scoped, autouse fixture (`tests/conftest._seed_plugin_registry`)
seeds the four first-party plugins to `PRODUCTION` automatically whenever
`POSTGRES_URL` is set, since essentially every ingestion-route test now
depends on it. Real deployments (and the Docker smoke test below) do need
the explicit CLI step — there's no pytest fixture running there.

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
  schemas/             Canonical DecisionEvent, Finding, GovernanceVerdict, System, ModelVersion,
                       ResolvedProtectedAttribute, PluginRegistration
  adapters/            Adapter[TPayload] port (+ adapter_id/version/governing_policy_id identity)
                       + SyntheticAdapter, CreditScorecardAdapter
  normalization/       Structural normalization pass
  protected_attributes/ classification.py (static rules) + resolver.py (ProtectedAttributeResolver)
  policy_engine/       Policy port + AlwaysAllowPolicy, DirectAttributeInInputsPolicy
  governance_engine/   Wraps a Policy's Finding into a Verdict
  plugins/             registry.py (in-process catalog), bootstrap.py (first-party imports),
                       sandbox.py (timeout + exception isolation), seed_registry.py (CLI)
  audit/               hash_chain.py (pure), evidence_store.py (Postgres), verify_chain.py
  db/                  session.py, migrate.py, models.py, repositories/
  api/
    app.py             Composition root -- builds routes from the plugin registry
    asgi.py            The only module that constructs the default instance
    dependencies.py    DI providers, typed against ports where ports exist
    middleware.py      MaxBodySizeMiddleware
    health.py          GET /healthz
    ingestion/         Registry-generated: one route per registered adapter
    admin/             POST/GET /v1/admin/systems, POST/GET/promote /v1/admin/plugins
infra/
  docker/              Dockerfile, docker-compose.yml
  migrations/          Numbered, Postgres-targeting .sql files
  ci/                  CI-only helper scripts (never used by the app itself)
tests/unit/            One test module per src module; DB-independent
tests/integration/     Full HTTP/DB round-trip tests; most need @requires_postgres
legacy_v1/             Superseded V1 prototype (reference only, not run)
```

## What M3 deliberately does not include

Every module has a docstring stating precisely which milestone owns the
capability it doesn't yet have. The short version: policy plurality (M4),
the full four-state verdict model with bindings/escalation/signing (M5),
async ingestion and population-level policies (M6), DB-backed/admin-
configurable protected-attribute classification rules (M5), real OS-level
plugin isolation beyond the timeout/exception sandbox (no milestone named
yet — see `docs/milestones/M3.md` §13.1), encryption at rest and retention
(M11), and comprehensive request-abuse protection beyond the `Content-Length`
check added during M0's finalization (M13). Building any of that now would
violate the milestone's own scope.

## What remains for M4

See [`docs/milestones/M3.md`](docs/milestones/M3.md) for the full
production-readiness review and design record. In short: M4 is policy
plurality — multiple policies whose Findings all genuinely contribute to
one Verdict, with disagreement aggregated and surfaced, not the
never-affects-the-Verdict side channel M3's shadow execution deliberately
is.
