# AI Governance Platform — M6: Async Population-Policy Evaluation Plane & Adverse Impact Ratio

A domain-agnostic observation-and-evaluation layer for LLM copilots, classical
ML models, rule engines, and hybrid decision systems. This repository
implements the frozen V2 architecture (`ARCH-GOV-002`) incrementally, per the
frozen implementation plan (`IMPL-GOV-001`).

**Current milestone: M6.** Adds a second, parallel governance pipeline
alongside the existing synchronous, per-event one: a `PopulationPolicy`
port that evaluates many `DecisionEvent`s for one `System` over one time
window, an explicitly-invoked batch job (`population_engine/run_policies.py`)
that runs it on a fixed, calendar-aligned schedule, and one concrete policy
— adverse impact ratio, the EEOC "four-fifths rule". **Both existing
ingestion routes and everything downstream of them are byte-for-byte
unchanged** — see
[`docs/architecture-mapping.md`](docs/architecture-mapping.md) for exactly
what each module does and does not yet do, and
[`docs/milestones/M6.md`](docs/milestones/M6.md) for the full design
review, hostile-review-pass corrections, and production-readiness report.

> **Do not point this milestone at real applicant/subject data.** The
> Evidence Store (and `protected_attribute_resolutions`) has no encryption
> at rest and no retention controls yet (M11), and there is still no auth in
> front of any endpoint — including the M6 admin surface below, whose
> entire content is a disparate-impact judgment about a real system — a
> platform-wide gap no milestone has closed yet (M13). Synthetic data only.

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

**Required before ingestion will accept anything**: seed the plugin
registry. Ingestion routes are generated from whichever adapters this
process's code has registered (`plugins/bootstrap.py`), but each one
rejects real traffic until its lifecycle state reaches `PRODUCTION` *and*
it has at least one active Policy Binding — a fresh database has none of
that yet, the same way it has no migrations applied until you run them:

```bash
python -m gov_platform.plugins.seed_registry --database-url "$GOV_PLATFORM_DATABASE_URL"
# ADAPTER credit-scorecard 0.2.0: promoted to PRODUCTION
# ADAPTER synthetic 0.1.0: promoted to PRODUCTION
# POLICY always-allow 0.1.0: promoted to PRODUCTION
# POLICY direct-attribute-in-inputs 0.1.0: promoted to PRODUCTION
# POLICY high-debt-ratio-gate 0.1.0: promoted to PRODUCTION
# BINDING credit-scorecard -> direct-attribute-in-inputs: created (severity=HIGH)
# BINDING credit-scorecard -> high-debt-ratio-gate: created (severity=MEDIUM)
# BINDING synthetic -> always-allow: created (severity=LOW)
# RULE FINANCE age: created (DIRECT)
# RULE FINANCE gender: created (DIRECT)
# RULE FINANCE marital_status: created (DIRECT)
# RULE FINANCE race: created (DIRECT)
# RULE FINANCE first_name: created (PROXY)
# RULE FINANCE zip_code: created (PROXY)
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
# Move "race" into feature_vector instead and this becomes "RECOMMEND_HOLD"
# (direct-attribute-in-inputs is bound at HIGH severity). Raise
# debt_to_income above 0.43 instead and it becomes "ESCALATE_FOR_REVIEW"
# (high-debt-ratio-gate is bound at MEDIUM severity) -- two independent
# policies, two different escalation outcomes for the same adapter.
```

**Managing the plugin registry** — list what's registered, or promote a
`DRAFT`/`SHADOW` candidate one lifecycle stage:

```bash
curl http://127.0.0.1:8000/v1/admin/plugins

curl -X POST http://127.0.0.1:8000/v1/admin/plugins/<registration-id>/promote
```

**Managing Policy Bindings** — which policy families govern which adapter,
and how severe a flag from each one is (drives the escalation outcome
above). Changing a binding takes effect on the very next ingestion
request, no restart needed:

```bash
curl http://127.0.0.1:8000/v1/admin/policy-bindings

curl -X POST http://127.0.0.1:8000/v1/admin/policy-bindings \
  -H "Content-Type: application/json" \
  -d '{"adapter_id": "credit-scorecard", "policy_id": "high-debt-ratio-gate", "severity": "HIGH"}'
# 409 -- already bound at MEDIUM by the seed step above; deactivate first
# to rebind, or use a policy_id not already bound to this adapter.

curl -X POST http://127.0.0.1:8000/v1/admin/policy-bindings/<binding-id>/deactivate
curl -X POST http://127.0.0.1:8000/v1/admin/policy-bindings/<binding-id>/activate
```

**Managing protected-attribute classification rules** — the DB-backed
ruleset `EvidenceStore`'s resolution path consults (not what
`DirectAttributeInInputsPolicy` itself checks — see
[`docs/milestones/M5.md`](docs/milestones/M5.md) §13.9 for that deliberate
divergence):

```bash
curl http://127.0.0.1:8000/v1/admin/protected-attribute-rules

curl -X POST http://127.0.0.1:8000/v1/admin/protected-attribute-rules \
  -H "Content-Type: application/json" \
  -d '{"domain": "HEALTHCARE", "attribute_name": "diagnosis", "classification": "DIRECT"}'
```

Verify the evidence hash chain independently at any time — optionally also
verifying every record's signature against a public key
(`python -m gov_platform.audit.signing --private-key <hex>` derives one
from `GOV_PLATFORM_SIGNING_PRIVATE_KEY`):

```bash
python -m gov_platform.audit.verify_chain --database-url "$GOV_PLATFORM_DATABASE_URL"
python -m gov_platform.audit.verify_chain --database-url "$GOV_PLATFORM_DATABASE_URL" --public-key <hex>
```

**Population-level policies (M6)** — a second, parallel governance
pipeline. Unlike the per-event policies above, `adverse-impact-ratio`
evaluates *many* decisions for one system at once, so it isn't run inline
with an ingestion request: bind it to a system, then invoke the batch job
whenever you want it evaluated (a real deployment would put this on a
cron/`CronJob`; this milestone doesn't build that scheduling itself — see
[`docs/milestones/M6.md`](docs/milestones/M6.md) §13.4). `adverse-impact-ratio`
is already seeded to `PRODUCTION` by the `seed_registry` step above — what's
missing on a fresh database is a *binding*, telling it which system to
monitor (deliberately not auto-seeded — see `plugins/seed_registry.py`'s
module docstring for why):

```bash
# <system-id> is the "id" field returned when credit-scorecard-prod was
# registered above (not its name) -- population_policy_bindings.system_id
# is a real foreign key into systems.id.
curl -X POST http://127.0.0.1:8000/v1/admin/population-policy-bindings \
  -H "Content-Type: application/json" \
  -d '{"system_id": "<system-id>", "population_policy_id": "adverse-impact-ratio"}'

curl http://127.0.0.1:8000/v1/admin/population-policy-bindings
curl -X POST http://127.0.0.1:8000/v1/admin/population-policy-bindings/<binding-id>/deactivate
```

Run the batch job — by default, evaluates every active binding against
"yesterday's full UTC day" (fixed and calendar-aligned, not a rolling
window — see `docs/milestones/M6.md` §13.13); `--window-start`/
`--window-end` (both together, ISO 8601 UTC) override this for a specific
past window instead:

```bash
python -m gov_platform.population_engine.run_policies --database-url "$GOV_PLATFORM_DATABASE_URL"
# FINDING <system-id> -> adverse-impact-ratio: CLEAR [2026-07-27, 2026-07-28)

# Re-running the same window is a clean, detectable no-op, not a duplicate:
python -m gov_platform.population_engine.run_policies --database-url "$GOV_PLATFORM_DATABASE_URL"
# SKIP <system-id> -> adverse-impact-ratio: window [...) already computed
```

Read the results — read-only; a `PopulationFinding` is only ever produced
by the batch job above, never created through this API:

```bash
curl http://127.0.0.1:8000/v1/admin/population-findings
curl "http://127.0.0.1:8000/v1/admin/population-findings?system_id=<a-system-id>"
```

Every finding is signed the same way evidence records are, but
independently verified (population findings aren't chained into
`evidence_chain` — see `docs/milestones/M6.md` §13.5):

```bash
python -m gov_platform.audit.verify_population_findings --database-url "$GOV_PLATFORM_DATABASE_URL" --public-key <hex>
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
seeds every first-party plugin (including `adverse-impact-ratio`, M6) to
`PRODUCTION` automatically whenever `POSTGRES_URL` is set, since
essentially every ingestion-route test now depends on it. Real
deployments (and the Docker smoke test below) do need the explicit CLI
step — there's no pytest fixture running there. A `PopulationPolicyBinding`
is never auto-seeded (by the fixture or by `seed_registry` — see that
module's docstring) — tests that need one create it against a system they
control, the same way a real operator would via the Admin API.

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
                       ResolvedProtectedAttribute, PluginRegistration, PolicyBinding,
                       ProtectedAttributeRule, PopulationFinding, PopulationPolicyBinding
  adapters/            Adapter[TPayload] port (+ adapter_id/version identity)
                       + SyntheticAdapter, CreditScorecardAdapter
  normalization/       Structural normalization pass
  protected_attributes/ classification.py (static rules) + resolver.py (ProtectedAttributeResolver;
                       optionally DB-backed via protected_attribute_rules -- see its docstring)
  policy_engine/       Policy port + AlwaysAllowPolicy, DirectAttributeInInputsPolicy,
                       HighDebtRatioGatePolicy
  governance_engine/   Aggregates every governing Policy's Finding into one Verdict, severity-driven
                       (GoverningPolicy bundles a Policy with its binding's PolicySeverity)
  population_engine/   PopulationPolicy port (M6) + AdverseImpactRatioPolicy; window.py (the
                       "Event Lake" windowed read); run_policies.py (the async-plane batch CLI)
  plugins/             registry.py (in-process catalog), bootstrap.py (first-party imports),
                       sandbox.py (timeout + exception isolation), seed_registry.py (CLI)
  audit/               hash_chain.py (pure), evidence_store.py (Postgres), verify_chain.py,
                       signing.py (Ed25519 evidence signing), verify_population_findings.py
  db/                  session.py, migrate.py, models.py, repositories/
  api/
    app.py             Composition root -- builds routes from the plugin registry
    asgi.py            The only module that constructs the default instance
    dependencies.py    DI providers, typed against ports where ports exist
    middleware.py      MaxBodySizeMiddleware
    health.py          GET /healthz
    ingestion/         Registry-generated: one route per registered adapter (unchanged by M6)
    admin/             systems, plugins (register/list/get/promote), policy-bindings
                       (create/list/get/activate/deactivate), protected-attribute-rules
                       (create/list/get), population-policy-bindings
                       (create/list/get/activate/deactivate), population-findings
                       (list/get, read-only)
infra/
  docker/              Dockerfile, docker-compose.yml
  migrations/          Numbered, Postgres-targeting .sql files
  ci/                  CI-only helper scripts (never used by the app itself)
tests/unit/            One test module per src module; DB-independent
tests/integration/     Full HTTP/DB round-trip tests; most need @requires_postgres
legacy_v1/             Superseded V1 prototype (reference only, not run)
```

## What M6 deliberately does not include

Every module has a docstring stating precisely which milestone owns the
capability it doesn't yet have. The short version: a general, pluggable
Evaluation Framework (one concrete metric shipped, not a configurable
framework — M8), real scheduling of the batch job (cron/`CronJob` —
deployment topology, M13-adjacent), a dedicated analytical store for the
"Event Lake" (the existing operational tables are reused, not
duplicated), severity/escalation for population findings (stay purely
informational — no Human Review Workflow, M9, exists yet for *any*
escalated output to go to), recomputing a historical window under today's
(changed) rules (a distinct "what-if" capability, not built),
domain/jurisdiction-keyed Policy Bindings (still only `adapter_id`-keyed —
M5's own deferral, unresolved by M6), unifying `DirectAttributeInInputsPolicy`
with the DB-backed protected-attribute rules (still M5's named
divergence), signing-key rotation and KMS/HSM custody (a single static
key, no more), the Compliance Dashboard (M10), real OS-level plugin
isolation beyond the timeout/exception sandbox (no milestone named yet —
see `docs/milestones/M3.md` §13.1), encryption at rest and retention
(M11), authentication in front of any endpoint including the two new M6
admin routes (no milestone has closed this yet — M13, flagged more
sharply at M6 than at any prior milestone — see
`docs/milestones/M6.md` §13.14), and comprehensive request-abuse
protection beyond the `Content-Length` check added during M0's
finalization (M13). Building any of that now would violate the
milestone's own scope.

## What remains after M6

See [`docs/milestones/M6.md`](docs/milestones/M6.md) for the full
production-readiness review and design record, including every deferred
item's reasoning. In short: M8 is a general Evaluation Framework (M6
ships one concrete population-level metric, not the framework); M9 is
the Human Review Workflow that finally gives an `ESCALATE_FOR_REVIEW`
verdict (M5) or a `FLAGGED` `PopulationFinding` (M6) somewhere to go.
