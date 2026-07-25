# AI Governance Platform — M0: Repository Foundation & Walking Skeleton

A domain-agnostic observation-and-evaluation layer for LLM copilots, classical
ML models, rule engines, and hybrid decision systems. This repository
implements the frozen V2 architecture (`ARCH-GOV-002`) incrementally, per the
frozen implementation plan (`IMPL-GOV-001`).

**Current milestone: M0.** A thin, real vertical slice through every
architectural seam — adapter → normalize → policy → verdict → evidence → API
— so every later milestone is additive, never structural. Nothing here is a
stub standing in for future work; it is the smallest honest version of each
seam. See [`docs/architecture-mapping.md`](docs/architecture-mapping.md) for
exactly what each module does and does not yet do.

> **Do not point this milestone at real applicant/subject data.** The
> Evidence Store has no encryption at rest, no auth in front of it, and no
> retention controls yet — those are M11, M13, and M11 scope respectively.
> M0 is for synthetic data only.

Version 1 (a single-domain prototype, superseded by this design) is preserved,
unmodified, in [`legacy_v1/`](legacy_v1/) for reference.

## Requirements

- Python 3.11+ (the implementation plan assumed 3.12; this environment has
  3.11.9, which is fully compatible with everything used here)
- Docker + Docker Compose, for the containerized run path

## Run locally

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash; use venv/bin/activate on Linux/macOS
pip install -e ".[dev]"
# Reproducible install instead: pip install -r requirements-lock.txt && pip install -e . --no-deps

uvicorn gov_platform.api.asgi:app --reload
```

Then:

```bash
curl http://127.0.0.1:8000/healthz
# {"status":"HEALTHY"}

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

## Run with Docker

```bash
docker compose -f infra/docker/docker-compose.yml up --build
```

## Development commands

```bash
ruff check src tests      # lint
mypy src                  # type-check (strict, src/ only)
pytest                    # unit + integration tests, with coverage
pre-commit install        # optional: run ruff + mypy on every commit
```

## Repository layout

```
src/gov_platform/
  config/            Settings (env-driven)
  observability/     Structured (JSON) logging
  schemas/           Canonical DecisionEvent, Finding, GovernanceVerdict
  adapters/          Adapter port + SyntheticAdapter (reference impl)
  normalization/      Structural normalization pass
  policy_engine/      Policy port + AlwaysAllowPolicy (reference impl)
  governance_engine/  Wraps a Policy's Finding into a Verdict
  audit/               Hash-chained, SQLite-backed Evidence Store
  api/                 FastAPI app factory, health + ingestion routes
infra/docker/          Dockerfile, docker-compose.yml
tests/unit/            One test module per src module
tests/integration/     Full HTTP round-trip tests
legacy_v1/              Superseded V1 prototype (reference only, not run)
```

## What M0 deliberately does not include

Every module above has a docstring stating precisely which architecture
milestone owns the capability it doesn't yet have. The short version: policy
plurality and disagreement handling (M4), the full four-state verdict model
with bindings/escalation/signing (M5), a real source-system adapter and
protected-attribute resolution (M2), Postgres and database-privilege-enforced
immutability (M1), and everything from Phase C/D of the implementation plan.
Building any of that now would violate the milestone's own scope.

## What remains for M1

See the end-of-milestone report for this build (Design Decisions /
"What remains for M1" section) for the specific handoff: formalizing System /
ModelVersion entities, migrating the operational store to Postgres, and
extracting the hash-chain logic into a standalone verification job.
