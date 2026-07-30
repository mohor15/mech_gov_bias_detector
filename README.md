# AI Governance Platform — M11: Encryption at Rest, Retention Tiers & Privilege Classification

A domain-agnostic observation-and-evaluation layer for LLM copilots, classical
ML models, rule engines, and hybrid decision systems. This repository
implements the frozen V2 architecture (`ARCH-GOV-002`) incrementally, per the
frozen implementation plan (`IMPL-GOV-001`).

**Current milestone: M11.** Completes architecture §13 ("Audit System")
with the three things every milestone since M0 has pointed at and never
built: **application-level encryption at rest** for a fixed, named list of
columns proven never to participate in any SQL comparison
(`evidence_chain.payload`, both review tables' `resolution_notes`,
`protected_attribute_resolutions.proxy_basis`); **retention tiers** for the
two tables that are simultaneously non-evidentiary and privilege-unlockable
(`shadow_findings`, `protected_attribute_resolutions`); and **privilege
classification** closing a gap M9 disclosed and left open — extending the
`evidence_chain`-style `REVOKE UPDATE, DELETE` lockdown to `systems`,
`model_versions`, `decision_events`, `findings`, `verdicts`, and
`verdict_findings`. Adds no new computation and (with two purely-additive
migrations) almost no new persisted state — its job is entirely about how
already-computed data is protected while it exists and removed once it no
longer needs to be. **Zero new external dependencies** — the `cryptography`
package this platform already depends on (added at M5 for signing) is
sufficient for the Fernet-based field encryption this milestone adds. See
[`docs/architecture-mapping.md`](docs/architecture-mapping.md) for exactly
what each module does and does not yet do, and
[`docs/milestones/M11.md`](docs/milestones/M11.md) for the full design
review, its own three-pass hostile-review record, and production-readiness
report.

> **Do not point this platform at real applicant/subject data.** Both new
> M11 protections are **opt-in and off by default**: application-level
> encryption only takes effect once an operator explicitly sets
> `GOV_PLATFORM_FIELD_ENCRYPTION_KEY`, and retention only runs against a
> table once an operator explicitly sets that table's own
> `RETENTION_DAYS_*` setting **and** invokes the purge CLI (there is no
> daemon/scheduler). A fresh deployment has neither configured, and stores
> everything exactly as every milestone before M11 already did. Storage-
> level encryption of the underlying Postgres volume — the literal, standard
> reading of "encryption at rest" — remains an infrastructure requirement
> this repository documents but cannot itself provision or verify (see
> below). And there is still no auth in front of any endpoint — including
> the ten M9 Human Review Workflow endpoints and the M10 dashboard.
> Encryption protects confidentiality against a compromised credential or
> an unencrypted backup; it does nothing about *authorization to read*
> through the API, which remains wide open. Still M13. Synthetic data only.

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
# POPULATION_POLICY adverse-impact-ratio 0.1.0: promoted to PRODUCTION
# POPULATION_POLICY disparity-significance-test 0.1.0: promoted to PRODUCTION
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

**Population-level policies (M6, generalized at M8)** — a second, parallel
governance pipeline. Unlike the per-event policies above, a population
policy evaluates *many* decisions for one system at once, so it isn't run
inline with an ingestion request: bind it to a system, then invoke the
batch job whenever you want it evaluated (a real deployment would put
this on a cron/`CronJob`; this milestone doesn't build that scheduling
itself — see [`docs/milestones/M6.md`](docs/milestones/M6.md) §13.4).
Two policies are seeded to `PRODUCTION` by the `seed_registry` step above:
`adverse-impact-ratio` (M6, a ratio threshold) and
`disparity-significance-test` (M8, a two-proportion statistical-
significance test — genuinely different in kind, not a second ratio
variant, see [`docs/milestones/M8.md`](docs/milestones/M8.md) §4.2). What's
missing on a fresh database is a *binding*, telling a policy which system
to monitor (deliberately not auto-seeded — see
`plugins/seed_registry.py`'s module docstring for why):

```bash
# <system-id> is the "id" field returned when credit-scorecard-prod was
# registered above (not its name) -- population_policy_bindings.system_id
# is a real foreign key into systems.id. "parameters" (M8) is optional --
# omit it entirely to use the policy's own built-in defaults.
curl -X POST http://127.0.0.1:8000/v1/admin/population-policy-bindings \
  -H "Content-Type: application/json" \
  -d '{"system_id": "<system-id>", "population_policy_id": "adverse-impact-ratio"}'

curl -X POST http://127.0.0.1:8000/v1/admin/population-policy-bindings \
  -H "Content-Type: application/json" \
  -d '{"system_id": "<system-id>", "population_policy_id": "disparity-significance-test", "parameters": {"z_critical": 2.5}}'

curl http://127.0.0.1:8000/v1/admin/population-policy-bindings
curl -X POST http://127.0.0.1:8000/v1/admin/population-policy-bindings/<binding-id>/deactivate
# Deactivating frees the (system_id, population_policy_id) pair for a new
# binding with different parameters (M8) -- there is still no PATCH/update
# endpoint; deactivate and create a new one to change parameters.
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

**Monitoring (M7)** — a real readiness check, additive alongside the
unchanged `/healthz`:

```bash
curl http://127.0.0.1:8000/readyz
# {"status":"READY"}   (200; 503 + {"detail":"database unreachable"} if the database can't be reached)
```

**Governance- and system-health metrics** — one JSON aggregate, computed
on demand from existing tables, no new persisted state. `since` scopes
only the governance-health half (recent activity) and defaults to the
last 24 hours; system-health fields describe current state and are never
windowed:

```bash
curl http://127.0.0.1:8000/v1/admin/metrics
curl "http://127.0.0.1:8000/v1/admin/metrics?since=2026-07-01T00:00:00Z"
# {
#   "system": {
#     "db_reachable": true, "db_latency_ms": 1.8,
#     "evidence_chain_latest_sequence_number": 57,
#     "plugin_counts": {"ADAPTER": {"PRODUCTION": 2}, ...},
#     "population_binding_staleness": {"<binding-id>": "2026-07-28T08:38:12Z", ...}
#   },
#   "governance": {
#     "window_start": "...", "window_end": "...",
#     "verdict_counts_by_status": {"ALLOW": 49, "RECOMMEND_HOLD": 1, ...},
#     "finding_counts_by_policy": {"direct-attribute-in-inputs": {"CLEAR": 7, "FLAGGED": 1}, ...},
#     "population_finding_counts_by_policy": {"adverse-impact-ratio": {"CLEAR": 38, "FLAGGED": 14}},
#     "shadow_disagreement_rate_by_policy": {"direct-attribute-in-inputs": 1.0}
#   },
#   "computed_at": "..."
# }
```

`since` must be timezone-aware — a naive timestamp (no `Z`/offset) is a
`422`, the same discipline every persisted timestamp in this codebase
already requires. A policy family with no comparable shadow/production
pairs in the window is omitted from `shadow_disagreement_rate_by_policy`
entirely, not reported as a misleading `0.0`; a `population_policy_binding`
that has never produced a finding shows up in
`population_binding_staleness` with a `null` value, not silently absent —
the loudest possible "this isn't running" signal, not an omission.

**Human Review Workflow (M9)** — a review is created automatically, not
through this API: `EvidenceStore.append` queues a `VerdictReview` for any
`Verdict` whose status is `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD`, and
`population_engine/run_policies.py` queues a `PopulationFindingReview` for
any `FLAGGED` `PopulationFinding` — each in its own transaction, decoupled
from the write it depends on (see
[`docs/milestones/M9.md`](docs/milestones/M9.md) §3.4). This API only
manages the resulting workflow state:

```bash
# List the open queue, oldest first; filter by status, and (verdict
# reviews only) by the underlying verdict's severity.
curl http://127.0.0.1:8000/v1/admin/verdict-reviews
curl "http://127.0.0.1:8000/v1/admin/verdict-reviews?status=OPEN&severity=RECOMMEND_HOLD"
curl http://127.0.0.1:8000/v1/admin/population-finding-reviews

# Claim, resolve, or release an abandoned claim -- <review-id> is the "id"
# field from a list/get response above, not a verdict_id/population_finding_id.
curl -X POST http://127.0.0.1:8000/v1/admin/verdict-reviews/<review-id>/claim \
  -H "Content-Type: application/json" -d '{"reviewer": "jane"}'
curl -X POST http://127.0.0.1:8000/v1/admin/verdict-reviews/<review-id>/resolve \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "jane", "resolution": "CONFIRMED", "notes": "a real, actionable disparity"}'
# "reviewer" on resolve must match whoever claimed it -- a cheap,
# pre-authentication integrity check, not a substitute for real auth (see
# the warning above); a mismatch, or a review that isn't currently claimed
# by anyone, is a 409, not a 500.
curl -X POST http://127.0.0.1:8000/v1/admin/verdict-reviews/<review-id>/release
```

A resolved review is never mutated in place — `resolution: "DISMISSED"`
today doesn't foreclose confirming the same underlying `Verdict`/
`PopulationFinding` matters later; a new review can still be queued for
it, superseding the old one without erasing it.

The reconciliation tool covers two gaps the live path alone can't: a
real deployment's pre-existing backlog from before M9 shipped, and the
narrow (and rare) case where the live path's own decoupled review-row
insert failed. Idempotent — safe to run once at rollout and safe to
re-run periodically thereafter (an ops cron entry, or manually after any
incident), including while ingestion is live:

```bash
python -m gov_platform.human_review.backfill_reviews --database-url "$GOV_PLATFORM_DATABASE_URL"
# verdict_reviews created: 3
# population_finding_reviews created: 1
```

**Compliance Dashboard (M10)** — three read-only pages, same origin as
every JSON endpoint above, no separate process or build step to run:

```
http://127.0.0.1:8000/dashboard                        Overview: system/governance health + readiness
http://127.0.0.1:8000/dashboard/population-findings    Population findings, filterable by system
http://127.0.0.1:8000/dashboard/reviews                Verdict reviews + population-finding reviews,
                                                        filterable by status/severity
```

Open any of the three in a browser — there is nothing to `curl` here beyond
confirming the shell HTML/static assets are served:

```bash
curl http://127.0.0.1:8000/dashboard
curl http://127.0.0.1:8000/dashboard/static/dashboard.css
curl http://127.0.0.1:8000/dashboard/static/dashboard.js
```

Read-only for this milestone — no claim/release/resolve actions from the
page itself (`docs/milestones/M10.md` §8.1); use the M9 Admin API endpoints
above for that. A dashboard packaging defect (a non-editable install
missing the static assets) degrades to "no dashboard," never "no
application" — see `docs/milestones/M10.md` §4.3/§8.6 and `api/dashboard.py`
for how.

**Encryption at rest, retention tiers & privilege classification (M11)** —
application-level field encryption for a fixed, named list of columns
(`evidence_chain.payload`, `verdict_reviews.resolution_notes`,
`population_finding_reviews.resolution_notes`,
`protected_attribute_resolutions.proxy_basis`), opt-in via one new setting:

```bash
# Generate a key -- must be Fernet's own format (32 url-safe-base64-encoded
# bytes), NOT SIGNING_PRIVATE_KEY's hex convention. No bespoke CLI helper is
# needed; Fernet.generate_key() already produces a ready-to-use value.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

export GOV_PLATFORM_FIELD_ENCRYPTION_KEY="<the generated key>"
```

Unset (the default): those columns are stored and read as plaintext,
exactly as every milestone before M11 already did, with a `WARNING`
(not `INFO`) logged on every startup naming this. There is **no**
ephemeral, auto-generated fallback the way `SIGNING_PRIVATE_KEY` has —
a fresh, per-process encryption key would make already-encrypted data
unrecoverable the moment the process restarts, an unrecoverable failure
mode signing's own fallback doesn't share. Encryption applies going
forward only — no backfill of any pre-M11 row; a version-prefix marker
(`"gpenc1:"`) distinguishes ciphertext from legacy plaintext at read time,
so turning the key on or off doesn't break reading older rows either way.

Verifying the hash chain against an encryption-enabled deployment now needs
the same key:

```bash
python -m gov_platform.audit.verify_chain --database-url "$GOV_PLATFORM_DATABASE_URL" \
  --encryption-key "$GOV_PLATFORM_FIELD_ENCRYPTION_KEY"
# Omitting --encryption-key against an encrypted chain fails cleanly with a
# named "cannot decrypt" result, not a crash.
```

Retention deletes rows older than a per-table configured window from
exactly two tables — `shadow_findings` and `protected_attribute_resolutions`,
the only tables in this schema that are both non-evidentiary and not
locked against deletion at the database-privilege level. Neither has a
numeric default (no external standard exists to source one from, unlike
the EEOC ratio or CFPB threshold this platform's other constants cite) —
a table with no configured window is skipped entirely by the purge tool,
logged as such:

```bash
export GOV_PLATFORM_RETENTION_DAYS_SHADOW_FINDINGS=90
export GOV_PLATFORM_RETENTION_DAYS_PROTECTED_ATTRIBUTE_RESOLUTIONS=365

# Requires DELETE privilege on both tables -- the app's own runtime role
# (gov_platform_app) does not have it as of migration 0026. Use the same
# admin/owner-privileged connection migrations use, never
# GOV_PLATFORM_DATABASE_URL.
python -m gov_platform.retention.purge_expired_records \
  --database-url "postgresql://postgres:<password>@localhost:5432/gov_platform"
# PURGED shadow_findings: 12 row(s) older than 2026-05-01T00:00:00+00:00 (90 day(s))
# SKIP protected_attribute_resolutions: no retention window configured
```

No daemon, no in-process scheduler — an explicitly-invoked, idempotent
tool, safe to run on any recurring cron/`CronJob` cadence an operator sets
up themselves (deployment-topology scope, unchanged, still M13).

**Migration `0025` needs a maintenance window** — unlike every other
migration in this repository. `GRANT`/`REVOKE` acquires an `ACCESS
EXCLUSIVE` lock in Postgres, and `0025` revokes `UPDATE`/`DELETE` on
`decision_events`, `findings`, and `verdicts` — this platform's actual
highest-throughput, request-path-critical tables. Apply it during a
planned, low-traffic window; migration `0026` (the two retention tables'
own privilege change plus their new indexes) carries no equivalent risk
and needs none.

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
ruff format --check src tests  # formatting (M7 on)
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

**M11**: a second, elevated connection (`ADMIN_DATABASE_URL`/
`admin_database_url`/`admin_db_engine`, gated by the `@requires_admin_postgres`
marker, same skip-cleanly-when-unset shape as `POSTGRES_URL`) is needed for
the retention tool's own tests and for proving the privilege lockdown's
positive control (the elevated connection can still delete; the restricted
`gov_platform_app` role cannot). CI already sets this (the same connection
migrations use); set it locally the same way to run those tests too:

```bash
export ADMIN_DATABASE_URL="postgresql://postgres:<password>@localhost:5432/gov_platform"
```

## Development commands

```bash
pre-commit install        # optional: run ruff + mypy on every commit
```

## Repository layout

```
src/gov_platform/
  config/              Settings (env-driven)
  observability/       logging.py (structured JSON logging); metrics.py (system-/governance-health
                       aggregate queries, M7 -- no new persisted state, no metrics-store technology)
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
                       signing.py (Ed25519 evidence signing), verify_population_findings.py,
                       encryption.py (M11 -- FieldEncryptor/NoOpFieldEncryptor, the gpenc1
                       marker, decrypt_field; pure, no DB)
  human_review/        backfill_reviews.py -- the M9 reconciliation tool (CLI); everything
                       else Human Review Workflow needs fits the existing per-entity
                       schema/repository/API convention directly (see schemas/human_review.py)
  retention/           purge_expired_records.py -- the M11 retention CLI (explicitly-invoked,
                       idempotent, no daemon); deletes rows older than a configured window
                       from shadow_findings/protected_attribute_resolutions only
  db/                  session.py, migrate.py, models.py, repositories/
  api/
    app.py             Composition root -- builds routes from the plugin registry
    asgi.py            The only module that constructs the default instance
    dependencies.py    DI providers, typed against ports where ports exist
    middleware.py      MaxBodySizeMiddleware
    health.py          GET /healthz (liveness only, unchanged since M0)
    readiness.py       GET /readyz (real DB-connectivity check, M7 -- additive, not a redefinition)
    dashboard.py       GET /dashboard, /dashboard/population-findings, /dashboard/reviews (M10 --
                       serves the static shell only; register_dashboard() is called from app.py
                       inside a try/except so a packaging defect can't take down the whole app)
    dashboard_static/  index.html, dashboard.css, dashboard.js (M10 -- vanilla JS, fetch()
                       against the JSON endpoints below, no build step, no framework)
    ingestion/         Registry-generated: one route per registered adapter (unchanged since M5)
    admin/             systems, plugins (register/list/get/promote), policy-bindings
                       (create/list/get/activate/deactivate), protected-attribute-rules
                       (create/list/get), population-policy-bindings
                       (create/list/get/activate/deactivate), population-findings
                       (list/get, read-only), metrics (GET, read-only, M7), verdict-reviews
                       and population-finding-reviews (list/get/claim/release/resolve, M9)
infra/
  docker/              Dockerfile, docker-compose.yml
  migrations/          Numbered, Postgres-targeting .sql files
  ci/                  CI-only helper scripts (never used by the app itself)
tests/unit/            One test module per src module; DB-independent
tests/integration/     Full HTTP/DB round-trip tests; most need @requires_postgres
legacy_v1/             Superseded V1 prototype (reference only, not run)
```

## What M11 deliberately does not include

Every module has a docstring stating precisely which milestone owns the
capability it doesn't yet have. The short version: **no encryption of
`decision_events.protected_attribute_refs`/`decision_output`** — the one
deliberate, load-bearing exclusion this milestone is built around;
`population_engine/window.py`'s SQL casts and groups by those columns
directly, so an opaque ciphertext blob would silently break every
population-policy finding (`docs/milestones/M11.md` §4.1). No encryption of
`reviewer` on either review table or `protected_attribute_resolutions.attribute_name`
— each participates in a repository-level SQL comparison
(`resolve()`'s own equality check; `list_by_decision_event`'s `ORDER BY`)
a non-deterministic cipher cannot survive; `reviewer` remains plaintext, a
real, disclosed gap, not a cost-free exclusion. No key rotation or KMS/HSM
custody for either the signing key or the new encryption key (unchanged
M5 scope boundary, applied consistently). No retroactive encryption of any
pre-M11 row (encryption applies going forward only, mirroring M5's own
"no retroactive signing" precedent). No chain pruning/checkpointing for
`evidence_chain`/`population_findings` — retention applies to exactly two
tables, not "old data" in general; deleting from a hash-chained or
signed-evidentiary table is either structurally destructive or would defeat
the guarantee those tables exist to provide, and no legal retention-period
requirement or storage-cost pressure has forced that harder question yet.
No new Admin API surface for retention/encryption status (mirrors
`run_policies.py`/`backfill_reviews.py`'s existing explicitly-invoked-CLI
precedent). No provider-specific storage-encryption infrastructure-as-code
(tier one is a documented deployment requirement this repository doesn't
itself provision Postgres to implement). No real authentication anywhere
(still M13, now a ninth-consecutive-milestone gap), and no
multi-tenancy/multi-plane deployment/mTLS (M13, unchanged).

## What remains after M11

See [`docs/milestones/M11.md`](docs/milestones/M11.md) for the full design
review, its three-pass hostile-review record, and production-readiness
report. In short: M12 is periodic report generation; M13 is authentication,
multi-tenancy, key rotation/KMS custody, and the several other cross-cutting
gaps every milestone since M2 has named and left open. `evidence_chain`/
`population_findings` chain-checkpointing (a prerequisite for ever pruning
either) remains the single largest disclosed gap this platform carries,
unassigned to any milestone until a concrete forcing requirement appears.
