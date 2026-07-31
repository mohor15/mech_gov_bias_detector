# Architecture → Module Mapping (M12)

Onboarding reference: which `ARCH-GOV-002` component each module implements,
and the precise boundary as of this milestone — what's real today vs. what's
deferred and to which milestone. Read alongside each module's own docstring,
which is the authoritative source; this table is the map, not the territory.

| Architecture component (§) | Module | Status as of M10 |
|---|---|---|
| §4.1 Ingestion Gateway & Adapter Framework | `adapters/base.py`, `adapters/synthetic.py`, `adapters/credit_scorecard.py` | Real, generic (`Adapter[TPayload]`) port + two implementations. **Unchanged by M6** — both ingestion routes, and everything downstream of them, are byte-for-byte identical to M5 (see M6-specific notes: the async plane M6 builds is additive and parallel, not a change to per-event ingestion). |
| §4.2 Normalization Service & Canonical Decision Event | `schemas/decision_event.py`, `normalization/service.py` | Real, minimal canonical schema; structural normalization only (whitespace, timezone, precision) — unchanged by M6. |
| §4.3 Protected Attribute Resolution Service | `schemas/protected_attribute.py`, `protected_attributes/classification.py`, `protected_attributes/resolver.py`, `schemas/protected_attribute_rule.py`, `db/repositories/protected_attribute_rule.py` | Unchanged by M6 for this service itself. **M6 adds a third, read-only consumer** of the DB-backed `protected_attribute_rules` table (`population_engine/window.py`, via its own direct repository call, not through `ProtectedAttributeResolver`) — see M6-specific notes on why, and on the reproducibility consequence that creates. |
| §6 Plugin Architecture | `adapters/base.py`, `policy_engine/base.py`, `population_engine/base.py`, `plugins/registry.py`, `plugins/bootstrap.py`, `plugins/sandbox.py`, `schemas/plugin_registration.py`, `db/repositories/plugin_registration.py`, `api/admin/plugins.py` | In-process registry + database-backed lifecycle state + a timeout/exception-isolation sandbox around every plugin call. **New in M6**: `PluginType.POPULATION_POLICY` — a third plugin kind, using the exact same registry/lifecycle mechanism `Adapter`/`Policy` already do, no second mechanism invented. `Adapter`/`Policy`/`PopulationPolicy` are now the three ports; Policy Bindings and Population Policy Bindings are separate, orthogonal axes (*which* trusted policies apply, not *whether* a policy's code is trusted). |
| §7 Policy Engine | `policy_engine/base.py`, `policy_engine/policies/*.py`, `schemas/policy_binding.py`, `db/repositories/policy_binding.py`, `api/admin/policy_bindings.py` | Real port + three reference policies, unchanged by M6. `Policy.evaluate(event) -> Finding`'s signature remains untouched — population-level evaluation is a deliberately separate, parallel port (`population_engine/base.py`, below), never a widened `Policy`. |
| §7/§8 Population-Level Policy Engine | `population_engine/base.py` (`PopulationPolicy`, `PopulationWindow`, `PopulationGroupCount`), `population_engine/window.py`, `population_engine/policies/adverse_impact_ratio.py`, `population_engine/policies/disparity_significance_test.py`, `population_engine/policies/_shared.py`, `population_engine/run_policies.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py`, `db/repositories/population_finding.py`, `db/repositories/population_policy_binding.py`, `api/admin/population_findings.py`, `api/admin/population_policy_bindings.py` | **New in M6, generalized at M8.** A third plugin port, `PopulationPolicy`, evaluating many `DecisionEvent`s for one `System` over one time window into one `PopulationFinding` — structurally parallel to, and never touching, `Policy`/`Finding`/`Verdict`. Two concrete policies ship: `adverse-impact-ratio` (M6, EEOC "4/5ths rule", 29 CFR § 1607.4(D)) and `disparity-significance-test` (M8, a two-proportion statistical-significance test, *Castaneda v. Partida* convention) — genuinely different kinds of judgment, proving the port generalizes, not a second ratio-threshold variant. **M8**: both policies' thresholds/minimum sample sizes are now admin-configurable per binding (`PopulationWindow.parameters`, resolved from the binding, with range validation and fallback to built-in defaults — see M8-specific notes), and `population_policy_bindings`' uniqueness is relaxed to a partial index scoped to `ACTIVE` (migration `0022`) so a binding can actually be deactivated and recreated with different parameters. Triggered by an explicitly-invoked batch CLI (`population_engine/run_policies.py`), not a daemon or in-process scheduler — this *is* "the async ingestion plane" (§4.1's citation), read as the plane population-level policies specifically need, not a redesign of per-event ingestion. `PopulationPolicyBinding` is `system_id`-keyed, a new table, deliberately separate from `policy_bindings`. See M6/M8-specific notes. |
| §8 Governance Engine | `governance_engine/engine.py`, `schemas/verdict.py` | Unchanged by M6. `GovernanceEngine`/`GovernanceVerdict` remain per-event; population-level results never flow through them. |
| §9 Monitoring | `observability/logging.py`, `observability/metrics.py`, `api/readiness.py`, `api/admin/metrics.py` | **Real as of M7.** `GET /readyz` — a real readiness check (database connectivity only; "adapter/source reachability" is currently vacuous, no first-party `Adapter` has a real external dependency yet), additive alongside the unchanged `/healthz`. `GET /v1/admin/metrics?since=` — a single, DB-query-backed JSON aggregate of system-health (current-state) and governance-health (windowed) signal, no new persisted state, no Prometheus/OpenTelemetry, no dashboard/UI (see M7-specific notes). |
| §10 Evaluation Framework | `population_engine/policies/adverse_impact_ratio.py`, `population_engine/policies/disparity_significance_test.py`, `population_engine/policies/_shared.py` | **Real as of M8.** Two concrete, genuinely different statistical tests (a ratio threshold and a significance test) plus admin-defined thresholds per binding — the two things `architecture-mapping.md`'s own M6-era citation named as missing. Still not a "bring your own statistical test" plugin surface beyond these two — that remains unscheduled until a concrete third need appears (see `docs/milestones/M8.md` §15). |
| §11 Compliance Dashboard | `api/dashboard.py`, `api/dashboard_static/index.html`, `dashboard.css`, `dashboard.js` | **Real as of M10.** Three read-only HTML views (Overview, Population Findings, Review Queue) rendering data M6/M7/M9 already compute and already expose via JSON — static HTML/CSS/vanilla JavaScript, same origin, `fetch()` against existing endpoints only. No new endpoint, no new table, no new external dependency, no build step. First UI this platform has ever built — see M10-specific notes. |
| §12 Human Review Workflow | `schemas/human_review.py`, `db/repositories/verdict_review.py`, `db/repositories/population_finding_review.py`, `api/admin/verdict_reviews.py`, `api/admin/population_finding_reviews.py`, `human_review/backfill_reviews.py` | **Real as of M9.** An `ESCALATE_FOR_REVIEW`/`RECOMMEND_HOLD` `GovernanceVerdict` (M5) and a `FLAGGED` `PopulationFinding` from either population policy (M6/M8) each get a reopenable `OPEN → IN_REVIEW → RESOLVED` workflow record (`VerdictReview`/`PopulationFindingReview`), created automatically in a transaction separate from the write it depends on, plus a five-endpoint Admin API to list/claim/release/resolve them and a standing, idempotent reconciliation tool covering both historical and live-path gaps. No new plugin port, no UI (M10), no notification mechanism, no reviewer authentication, no signing of the resolution itself — see M9-specific notes. |
| §13 Audit System | `audit/hash_chain.py`, `audit/evidence_store.py`, `audit/verify_chain.py`, `audit/signing.py`, `audit/verify_population_findings.py`, `audit/encryption.py` | Real hash-chained Postgres ledger for per-event evidence, append-only enforced at the database-privilege level, plus a standalone chain-verification job/CLI — unchanged by M6/M8/M9. **New in M6**: `population_findings` gets the identical append-only privilege lockdown (`REVOKE UPDATE, DELETE`, migration `0015`) and is signed (reusing `audit/signing.py` unchanged) — but is **not chained** into `evidence_chain` (no `previous_hash`, no single `decision_event_id` it belongs to). `audit/verify_population_findings.py` is a separate, parallel verifier — a plain content hash over each finding's own canonical payload (including `classification_snapshot`), not `hash_chain`'s chained variant. **New in M8**: `population_finding_hash` dumps with `exclude_none=True`, so `parameters_used` (nullable, un-backfilled, migration `0021`) is omitted from the hashed payload for every finding signed before this field existed, rather than changing their recomputed hash and silently invalidating their already-issued signatures — the first time this codebase has added a field to an already-populated signed model (see `docs/milestones/M8.md` §4.5/§13.18). **M9 deliberately does not extend this system**: `verdict_reviews`/`population_finding_reviews` are ordinary, unsigned, mutable workflow state, not evidentiary records — the `Verdict`/`PopulationFinding` each references remains exactly as signed/chained/immutable as before; whether a review's resolution should itself become signed evidence was a real, approved-as-deferred decision, not an oversight (`docs/milestones/M9.md` §9.2). **New in M11 — encryption at rest is real**: application-level field encryption (`audit/encryption.py`, `FernetFieldEncryptor`/`NoOpFieldEncryptor`) for a fixed, named list of columns proven never SQL-compared — `evidence_chain.payload` (hash-then-encrypt: `record_hash` still commits to the plaintext payload, unchanged), `verdict_reviews`/`population_finding_reviews`' `resolution_notes`, and `protected_attribute_resolutions.proxy_basis`. Opt-in via `Settings.FIELD_ENCRYPTION_KEY`, no ephemeral fallback (unlike signing). `verify_chain.py` gains `--encryption-key`; a decrypt failure is a specific, catchable `FieldDecryptionError`, never an unhandled crash. Key rotation/KMS custody remain unassigned, still deferred, for both the signing key and the new encryption key — see M11-specific notes. |
| §14 Reporting | `reporting/compliance_report.py`, `reporting/generate_report.py` | **Real as of M12.** A bounded, closed-window (`[window_start, window_end)`) query over exactly five tables — `verdicts`, `findings`, `population_findings`, `verdict_reviews`, `population_finding_reviews` — none of which is retention-eligible (M11 §5.2) and none of which any code path ever deletes from, so a report for a given window is guaranteed byte-reproducible on regeneration regardless of M11 retention activity. Structurally parallel to, but never importing from or modifying, `observability/metrics.py` (M7) — that module's own `get_governance_health_metrics` computes an open-ended `[since, now())` window, structurally incompatible with a closed historical one. An explicitly-invoked CLI (`python -m gov_platform.reporting.generate_report`), no daemon, exporting JSON (primary, via `audit/hash_chain.canonical_json` for deterministic regeneration) or CSV (five flat files, opt-in) — no PDF (see M12-specific notes). No new plugin port, no new endpoint, no new database credential tier, no new `Settings` field, no persistence of generated reports inside this platform. |
| §15 APIs | `api/health.py`, `api/readiness.py`, `api/ingestion/routes.py`, `api/admin/systems.py`, `api/admin/plugins.py`, `api/admin/policy_bindings.py`, `api/admin/protected_attribute_rules.py`, `api/admin/population_policy_bindings.py`, `api/admin/population_findings.py`, `api/admin/metrics.py`, `api/admin/verdict_reviews.py`, `api/admin/population_finding_reviews.py`, `api/app.py`, `api/asgi.py` | Ingestion routes are registry-generated (one per registered adapter — currently `synthetic` and `credit-scorecard`), **unchanged by M7/M8/M9/M11**, same response shape; `/healthz` also unchanged. `GET /readyz` and `GET /v1/admin/metrics` (M7) unchanged by M8/M9/M11 — every JSON response shape any client sees is byte-for-byte identical to before M11; encryption/decryption happens entirely at the repository read/write boundary. **New in M9**: ten endpoints across two new routers (`verdict-reviews`, `population-finding-reviews`; `list`/`get`/`claim`/`release`/`resolve` each) — read-only except for the three workflow-transition actions, which never load new code or compute a new result, the same boundary every Admin API in this codebase draws. `claim`/`release`/`resolve` translate a repository-raised `ValueError` conflict into a `409` via an explicit handler in each route, not the codebase's existing global `ValueError → 422` handler. No endpoint anywhere has authentication yet, including these ten — the same standing gap M5/M6/M7/M8 named, now a ninth-consecutive-milestone-and-counting gap (M11 does not close it: encryption protects confidentiality against a compromised credential, not authorization to read through this API). `app.py` is still the side-effect-free factory; **new in M11**, it also builds one `FieldEncryptor` from `Settings.FIELD_ENCRYPTION_KEY` and threads it into every repository that needs it. No new endpoint of any kind added by M11 — see M11-specific notes. |
| §16 Database Design | `db/session.py`, `db/models.py`, `db/migrate.py`, `db/repositories/`, `schemas/system.py`, `schemas/model_version.py`, `schemas/protected_attribute.py`, `schemas/plugin_registration.py`, `schemas/policy_binding.py`, `schemas/protected_attribute_rule.py`, `schemas/population_finding.py`, `schemas/population_policy_binding.py`, `schemas/human_review.py` | Real Postgres, formalized via numbered `.sql` migrations (schema authority) + a repository layer per entity. **New in M7**: three indexes (migrations `0017`–`0019`) supporting the windowed metrics-aggregate read pattern. **New in M8**: two additive nullable columns and one non-purely-additive constraint relaxation (migration `0022`, narrowly justified — see `docs/milestones/M8.md` §4.4/§13.12). **New in M9**: two new tables, `verdict_reviews`/`population_finding_reviews` (migrations `0023`–`0024`) — purely additive `CREATE TABLE`, no existing table altered, unlike M8's one necessary exception. Each gets ordinary `GRANT` privileges (mutable workflow state, not evidentiary output — unlike `evidence_chain`/`population_findings`' lockdown), an explicit `ON DELETE RESTRICT` foreign key to its subject, and a **partial** unique index (`one_open_..._per_...`, scoped to non-`RESOLVED` rows) rather than a plain `UNIQUE` — the identical fix M8's own migration `0022` made for `population_policy_bindings`, applied here from the start rather than discovered after the fact. `db/session.create_db_engine`'s bounded connection timeout (M7) unchanged. SQLAlchemy models are query-time mappings only — never used to generate DDL. **New in M11**: two more purely-additive migrations, `0025`/`0026` — no `ALTER` of any existing column, no data rewrite, only privilege `GRANT`/`REVOKE` and two new indexes. `0025` extends `evidence_chain`'s own append-only lockdown to `systems`, `model_versions`, `decision_events`, `findings`, `verdicts`, `verdict_findings` (closing `docs/milestones/M9.md` §9.5's disclosed gap); `0026` revokes `DELETE`/`UPDATE` from `gov_platform_app` on `shadow_findings`/`protected_attribute_resolutions` and adds `idx_shadow_findings_evaluated_at`/`idx_protected_attribute_resolutions_resolved_at`. Six ordinary admin-configuration tables (`plugin_registrations`, `policy_bindings`, `protected_attribute_rules`, `population_policy_bindings`, `verdict_reviews`, `population_finding_reviews`) keep their full, unrevoked `DELETE` grant — deliberately, since none is retention-eligible or evidentiary. **New in M12**: one more purely-additive migration, `0027` — two indexes, `(status, resolved_at)` on `verdict_reviews`/`population_finding_reviews`, supporting the one new query pattern M12's own reporting CLI introduces ("which reviews were resolved within this window"). No new table, no `ALTER` of any existing column, no privilege change. Multi-tenancy and the analytical-warehouse split remain later milestones. |
| §17 Deployment Architecture | `infra/docker/` | Single container, single service; assumes an external Postgres — unchanged by M7/M8/M9/M11. A real orchestrator can use `GET /readyz` as an actual readiness probe rather than reusing `/healthz` (liveness only) for both purposes. **M11**: storage-level encryption of that external Postgres volume — the literal, standard reading of "encryption at rest" for the primary datastore — is a documented deployment requirement this repository cannot itself provision or verify (no Postgres provisioning exists in this repository's own infrastructure); `retention/purge_expired_records.py`'s own recurring-schedule invocation (a cron/`CronJob` an operator sets up) is real scheduling scope, also unbuilt here, for the identical reason `population_engine/run_policies.py`'s batch cadence already is. **M12**: `reporting/generate_report.py`'s own recurring-schedule invocation is the identical, third instance of this same unbuilt scope — no daemon, no in-process scheduler, an operator's own cron/`CronJob` cadence, unchanged. Multi-plane topology, multi-tenancy, and mTLS are M13. |

## M12-specific notes

- **The report's content is scoped to exactly five tables, and that scope
  is what makes every report immune to M11's retention purge — not an
  accident, a checked design property.** `verdicts`, `findings`,
  `population_findings`, `verdict_reviews`, `population_finding_reviews`
  are the only tables the report's five queries touch; none is
  retention-eligible (M11 §5.2 names exactly two: `shadow_findings`,
  `protected_attribute_resolutions`) and none is ever deleted from in
  practice. A report generated for a historical window today and
  regenerated for the identical window after any amount of M11 retention
  activity is therefore guaranteed to read the identical underlying rows
  both times — the same class of interaction M11's own hostile-review
  pass could only *disclose*, not avoid, for M7's `?since` parameter,
  avoided here entirely by scope. See `docs/milestones/M12.md` §4.3.
- **`observability/metrics.py` is read for shape, not reused for code.**
  `get_governance_health_metrics(engine, *, since)` computes an
  open-ended `[since, now())` window — every call answers "through this
  exact instant," never "what did it look like during some specific,
  already-closed past period." A monthly compliance report needs the
  second kind of question. `reporting/compliance_report.py` ships its
  own, small, self-contained bounded-window query functions rather than
  reopening a module this project's own standing discipline (M8 §13.14,
  M9 §9.1, M11 §4.3) has repeatedly declined to reopen for an unrelated
  milestone's need — field names and nesting still mirror
  `GovernanceHealthMetrics` deliberately, so the two aggregate surfaces
  stay recognizable to the same operator.
- **No PDF — this milestone's own highest-stakes call, resolved in favor
  of the stdlib `json`/`csv` modules already relied on elsewhere in this
  codebase.** M10's own citation trail names a PDF only as an
  *illustrative example* of "periodic, document-shaped, non-interactive,"
  never repeated as a concrete format requirement anywhere else in this
  platform's record. Introducing this platform's first genuinely new
  rendering/formatting dependency (`reportlab`, `weasyprint`, `fpdf2`, or
  similar) was judged to need a concrete, current forcing case, not an
  example in a different milestone's design doc three milestones prior —
  see `docs/milestones/M12.md` §12.1.
- **CSV export writes five files, not four — `ReviewOutcomeCounts` holds
  two independently-keyed dicts, not one.** A verdict-review resolution
  and a population-finding-review resolution are different key spaces
  with no shared row shape; splitting them into
  `<prefix>-verdict-reviews.csv`/`<prefix>-population-finding-reviews.csv`
  keeps every exported file a genuinely flat table with no internal
  sections — found and corrected during this milestone's own second
  hostile-review pass, before implementation began.
- **`reporting/generate_report.py`'s `--database-url` connection uses
  `db.session.create_db_engine`, never a bare `create_engine` — stated
  explicitly in the design, not left for an implementer to infer by
  analogy.** This is the exact defect class that caused one of M11's own
  two CI failures (`ModuleNotFoundError: No module named 'psycopg2'`, from
  a bare `postgresql://` URL reaching an unnormalized `create_engine`);
  every CLI in this codebase that takes `--database-url` falls into one of
  exactly two groups (`create_db_engine`, or `db/migrate.py`'s own
  deliberate `create_engine` exception), and M12's own second
  hostile-review pass found the first design draft ambiguous about which
  group this milestone's CLI belonged to before implementation ever
  started.
- **Two real bugs lived in the frozen design's own SQL (§5.1), invisible
  to lint/mypy/a Postgres-less test run, and were found only once this
  milestone's queries were actually executed against a real Postgres
  instance.** A bare `id` in the `--system-id`-filtering subquery
  (`SELECT id FROM decision_events de JOIN model_versions mv ...`) is
  ambiguous between the two joined tables' own `id` columns — Postgres
  rejects it outright. Separately, `:system_id IS NULL OR ...` left one
  parameter occurrence with no inferable type for Postgres's extended
  query protocol (`IS NULL` accepts any type), failing with
  `AmbiguousParameter`. Both are pure syntax fixes (`de.id`; `CAST(:system_id
  AS text) IS NULL`) that change no join, filter, or semantic behavior —
  not design contradictions. This milestone's own first-pass
  production-readiness review, performed with no Postgres available,
  concluded "no implementation-time bug was found"; that conclusion was
  wrong, and `docs/milestones/M12.md`'s own "Production-Readiness Review"
  preserves it, corrected, rather than deleting the record. All 43 new
  M12 tests pass against a real, freshly-migrated Postgres 16 instance.

## M11-specific notes

- **Exactly four columns are application-encrypted, traced directly
  against every repository method and SQL statement in this codebase, not
  assumed from the API router layer alone.** `evidence_chain.payload`,
  `verdict_reviews.resolution_notes`, `population_finding_reviews.resolution_notes`,
  `protected_attribute_resolutions.proxy_basis`. Every other candidate
  column was excluded for a specific, checked reason:
  `decision_events.protected_attribute_refs`/`decision_output` because
  `population_engine/window.py`'s SQL casts and groups by them directly;
  `reviewer` (both review tables) because `resolve()`'s own conditional
  `UPDATE ... WHERE ... AND reviewer = :reviewer` (M9's identity-continuity
  check) cannot survive comparison against Fernet's non-deterministic
  ciphertext; `protected_attribute_resolutions.attribute_name` because
  `list_by_decision_event`'s `ORDER BY` depends on its plaintext order. See
  `docs/milestones/M11.md` §4.1/§5.1.
- **Hash-then-encrypt, not encrypt-then-hash — the hash chain's own
  guarantee is completely unaffected by encryption.** `EvidenceStore.append`
  computes `record_hash` over the plaintext canonical payload exactly as
  every milestone before M11 already did; only the resulting JSON string
  is encrypted before being written to the `payload` column. `verify_chain`'s
  hash-recomputation *logic* needed zero changes — it already operated on
  the decrypted `EvidenceRecord.payload` dict, never on raw column bytes.
  What *did* need real, minimal plumbing (a first-draft claim of "zero code
  changes" that was traced and found false before implementation began):
  `EvidenceStore` gaining an `encryptor` collaborator, `verify_chain.py`
  gaining `--encryption-key`, and a specific, catchable `FieldDecryptionError`
  distinguishing "cannot be read" from an actual hash-mismatch tamper
  finding.
- **No ephemeral, auto-generated key fallback for encryption — a
  deliberate, asymmetric divergence from `audit.signing.load_signer`'s own
  precedent.** A signing key with no configured value generates fresh and
  signs fine within one process's lifetime (the only cost: a different
  process can't cross-verify). An encryption key with the identical
  fallback would encrypt real data under a key that exists nowhere
  durable, and lose access to it on the very next process restart — an
  unrecoverable, self-inflicted data-loss bug, not a graceful degradation.
  `FIELD_ENCRYPTION_KEY` unset simply means encryption is off, logged at
  `WARNING` (not `INFO`) on every affected startup.
- **Retention applies to exactly two tables, not "old data" in general —
  and the reason is structural, not a scope preference.** `evidence_chain`
  is hash-chained; deleting any row breaks `previous_hash` continuity for
  every row after it. `population_findings` is signed, evidentiary output
  with the identical "a recompute must be a new row, never a silent
  rewrite" guarantee a `Verdict` has. The six operational tables migration
  `0025` locks down are the *normalized record of exactly what
  `evidence_chain.payload` already embeds* — deleting from them while the
  full content survives permanently inside the chain would reduce only
  queryable surface, not actual data retained, a half-measure this
  document declines to build and call "retention." `shadow_findings`/
  `protected_attribute_resolutions` are retention-eligible specifically
  because they are simultaneously non-evidentiary *and* not locked against
  deletion at the privilege level — see `docs/milestones/M11.md` §4.2.
- **`protected_attribute_resolutions`' inclusion in retention scope rests
  on a *conditional* reproducibility premise, disclosed rather than
  silently assumed.** The M2-era claim ("derived, reconstructible data...
  re-running the resolver reproduces it") predates M5's switch to a live,
  DB-backed `protected_attribute_rules` table — granted `UPDATE`/`DELETE`
  and carrying no `population_findings.classification_snapshot`-equivalent.
  Under today's Admin API (create/list/get only, no rule-editing endpoint)
  this is a low-probability, not a zero-probability, risk. The raw
  attribute values a purged row's classification was computed over are
  never actually at risk regardless — they persist forever in
  `decision_events.protected_attribute_refs`/`evidence_chain.payload`,
  neither of which retention ever touches. See `docs/milestones/M11.md`
  §4.4.
- **The privilege lockdown's own claim is scoped to exactly ten tables,
  not "this schema" as a whole — a real self-contradiction this
  milestone's own second design-review pass found and corrected before
  implementation.** Six ordinary admin-configuration tables
  (`plugin_registrations`, `policy_bindings`, `protected_attribute_rules`,
  `population_policy_bindings`, `verdict_reviews`,
  `population_finding_reviews`) retain the full `DELETE` grant given at
  their own originating migration, unchanged by M11 — correctly so, since
  none of the six is retention-eligible or evidentiary. An earlier design
  draft claimed the application role "holds no deletion capability over
  anything in this schema at all," which these six tables' own grants
  directly contradict; the corrected, implemented claim is scoped to the
  ten tables M11 actually classifies.
- **The retention tool's elevated connection is a real, if narrow, new
  operational secret — reusing the migration-owner credential, not a new
  Postgres role.** Unlike a migration credential (used rarely, transiently,
  under direct supervision), retention is designed to run on a recurring
  cron/`CronJob` cadence, so this same schema-owning secret must live
  persistently wherever that schedule runs — a materially larger, more
  routine exposure than the original "avoid a fourth credential tier"
  framing weighed. An operator provisioning a narrower,
  `SELECT`+`DELETE`-only role scoped to exactly the two retention-eligible
  tables is actively encouraged, not merely permitted, precisely because of
  that exposure — see `docs/milestones/M11.md` §12.11.
- **Implementation-time finding, not a design contradiction:**
  `EvidenceStore.all()` decrypts every row before returning any of them
  (a pre-existing, eager, list-returning contract), so a decrypt failure
  is caught wrapping the whole fetch inside `verify_chain_from_database`,
  not inside `verify_chain()`'s own per-record hash-checking loop the way
  the design document's prose read at a literal level. The failing
  record's own `sequence_number` is still named in the resulting
  `ChainVerificationResult.detail`, so the result stays specific and
  actionable; `checked_count` just can't reflect hash-verification
  progress that never got to run in this path.
- **Chain-checkpointing for `evidence_chain`/`population_findings`
  remains completely unbuilt — the single largest disclosed gap this
  milestone leaves open**, unassigned to any future milestone until a
  concrete legal retention-period requirement or real storage-cost
  pressure forces the question. See `docs/milestones/M11.md` §4.2/§12.9.

## M9-specific notes

- **The headline correction, found on this milestone's own hostile-review
  pass: review-row creation is deliberately decoupled from the write it
  depends on.** The first design draft recommended creating a
  `VerdictReview`/`PopulationFindingReview` inside the *same* transaction
  as `EvidenceStore.append`/`run_policies.py`'s finding commit. A bug in
  this new, non-essential workflow code would have rolled back the
  hash-chained evidence record for a real, already-made governance
  decision — this platform's single most important guarantee, put at risk
  by a feature that has nothing to do with evidence integrity. Fixed
  before implementation: a **separate** transaction, called only after the
  more important write's own commit succeeds, with its own failure logged
  and swallowed rather than propagated. See `docs/milestones/M9.md` §3.4.
- **Decoupling reopens a narrow race with the reconciliation tool, found
  during a *second* hostile-review pass.** Both the live path and
  `human_review/backfill_reviews.py` can race to create a review for the
  same subject; a plain `INSERT` would let whichever writer loses that
  race fail outright. Both use `INSERT ... ON CONFLICT ... DO NOTHING`
  instead, and the reconciliation tool is reframed from a one-time
  backfill script into a standing tool safe to re-run periodically,
  specifically to serve as this ongoing safety net (not just a
  historical-catch-up step) — see `docs/milestones/M9.md` §3.4/§3.5.
- **`RESOLVED` is terminal for one review row, never for the verdict/
  finding it references — a partial unique index, not a plain `UNIQUE`.**
  The first design draft reproduced, in a brand-new table, the exact
  defect M8's migration `0022` already fixed once for
  `population_policy_bindings`: a plain constraint that permanently
  forecloses a legitimate future need (reopening a previously-resolved
  review) the moment one appears. Fixed before implementation, applying
  M8's own lesson from the start rather than discovering it again after
  the fact — see `docs/milestones/M9.md` §3.2.
- **An explicit `IN_REVIEW → OPEN` release transition, added after the
  first design draft's three-state, no-path-backward workflow was found
  to have no recovery from an abandoned claim.** Given this platform has
  no authentication to even identify who claimed an item for follow-up, an
  unrecoverable claim was a realistic, not hypothetical, failure mode —
  see `docs/milestones/M9.md` §3.3.
- **Two genuinely pre-existing defects were found as a byproduct of this
  milestone's own design, not introduced by it, and are deliberately not
  fixed inside M9** (the same "found and documented, not silently folded
  in" discipline M8 §13.20 established for the identical class of
  discovery): `verdicts`/`findings`/`decision_events`/`model_versions`/
  `systems`/`verdict_findings` lack the `REVOKE UPDATE, DELETE`
  database-privilege lockdown `evidence_chain`/`population_findings` have
  — true since M1/M5, found only because M9 is the first milestone to add
  a real foreign key pointing at `verdicts`; and
  `PopulationPolicyBindingRepository.set_lifecycle_state` (and
  `PolicyBindingRepository`'s identical twin) use a read-then-write
  pattern with no conditional-update protection against a concurrent
  lifecycle transition, found only because M9's own `claim`/`release`/
  `resolve` needed a materially stronger pattern. Both documented as
  verified, outstanding candidates for a dedicated follow-up
  (`docs/milestones/M9.md` §9.5/§9.6).
- **No authentication was added anywhere, including the ten new M9
  endpoints** — consistent with every existing endpoint, but named more
  sharply than at any prior milestone: this is the first milestone where
  an unauthenticated caller can fabricate a specific, named person's
  professional judgment about a real bias finding. The one in-scope
  mitigation is a non-authentication sanity check — `resolve` must restate
  and match the `reviewer` who claimed the item — which catches accidental
  cross-wiring, not a malicious actor, and does not close this gap.

## M8-specific notes

- **A generalization milestone, not a new pipeline.** M8 does to
  `population_engine` what M4 did to `Policy`/`GovernanceEngine` and M5
  did to `PolicyBinding`: ship a second concrete implementation of an
  already-general-enough port, and move a judgment call (a threshold)
  from code onto an admin-configurable binding. No new plugin port, no
  new persisted-output table, no rewrite of the Event Lake read pattern.
- **`DisparitySignificanceTestPolicy` is a genuinely different kind of
  judgment, not a second ratio-threshold variant.** A two-proportion
  z-test answers "is this disparity plausibly noise," where
  `adverse-impact-ratio` answers "is this disparity practically large" —
  the same "different kind of judgment" discipline M4 used picking
  `HighDebtRatioGatePolicy` over a second fairness-check variant. No new
  external dependency — the z-statistic is closed-form arithmetic.
- **Two statistical-validity guards beyond a flat sample-size floor**,
  found scrutinizing the z-test math during this milestone's own
  hostile-review pass: an expected-cell-count check (a group can clear
  `minimum_group_size` on raw count alone while still having a rate too
  extreme for the normal approximation to be valid) and a degenerate-
  variance guard (never actually reachable once the expected-cell-count
  check holds, kept as defense in depth).
- **Admin-configurable parameters thread through `PopulationWindow`, not
  a widened `evaluate()` signature.** `PopulationWindow` already existed
  to carry "everything this evaluation needs beyond the window's raw
  data" (`classification_snapshot` set this precedent at M6) — a
  `parameters` field is the same pattern for a second kind of context,
  not a new one. Each policy validates its own resolved parameters
  against a sane range, falling back to its built-in default rather than
  silently proceeding with a nonsensical value or raising.
- **The headline hostile-review-pass finding: adding a field to an
  already-signed, already-populated model is a genuinely new problem
  class for this codebase.** `parameters_used`'s first draft (an
  always-present field, backfilled `NOT NULL DEFAULT '{}'`) would have
  silently invalidated every `PopulationFinding` signed before M8 the
  first time `verify_population_findings` ran afterward — `population_finding_hash`
  hashes the whole model, so a new key changes the hash for every
  historical record too. Fixed with a nullable, un-backfilled column and
  `exclude_none=True` on the hash. Every prior signed-schema change
  (`classification_snapshot` included) landed before any record existed
  under the older shape, so this exact conflict never previously arose.
- **The schema fix that makes a binding's parameters changeable requires
  an application-code fix too.** Relaxing `population_policy_bindings`'
  uniqueness to a partial index scoped to `ACTIVE` (migration `0022`) is
  necessary but not sufficient: `create_population_policy_binding`'s own
  conflict pre-check called `get_by_identity`, which ignores
  `lifecycle_state` and would still reject recreating a deactivated
  binding. Fixed with a new `get_active_by_identity` method, added rather
  than changing `get_by_identity`'s existing, lifecycle-blind semantics,
  which other repositories and `plugins/seed_registry.py` depend on
  unchanged.
- **A genuinely pre-existing, previously-undiscovered defect was found as
  a side effect of this review, not introduced by it**: `policy_bindings`
  (M5) has the identical lifecycle-blind conflict check and the identical
  plain (non-partial) uniqueness constraint `population_policy_bindings`
  had before this fix — meaning `PolicyBinding.severity` has likely never
  actually been changeable via "deactivate and recreate" in this
  platform's history. Deliberately left unfixed inside M8 (M5's scope,
  not the Evaluation Framework) — documented and flagged as a candidate
  for a small, dedicated follow-up.
- **No cross-policy aggregation mechanism.** Each `PopulationPolicy`'s
  finding for a given `(system_id, window)` stays its own independent,
  parallel row, the same "structurally separate, never combined"
  relationship `shadow_findings` has to `findings` — building a
  combining mechanism now, with exactly two policies and no concrete
  requirement to combine their outputs, would be the same premature
  generalization this project has declined at every prior opportunity.

See `docs/milestones/M8.md` for the full design review, hostile-review-
pass corrections, and production-readiness report.

## M7-specific notes

- **"Monitoring" is a minimal, DB-query-backed JSON endpoint, not a
  Prometheus/OpenTelemetry stack.** This platform has one deployment
  environment and no established scraping infrastructure to integrate
  with — introducing real metrics infrastructure now would be designing
  against a deployment topology this project has never had a real case
  for, the same "no second deployment environment" reasoning M5 already
  applied to signing-key custody and M6 applied to a dedicated analytical
  store. See `docs/milestones/M7.md` §13.1 — the highest-stakes call in
  that document.
- **No dashboard, no UI.** "Dashboards" in architecture §9's own citation
  is read as describing what a *future* consumer (M10's Compliance
  Dashboard) renders from M7's metrics, not something M7 itself
  delivers — this platform has never built a UI anywhere in seven
  milestones. See `docs/milestones/M7.md` §13.2.
- **`/readyz` is additive; `/healthz` is byte-for-byte unchanged.**
  Mirrors this project's own standing discipline for an existing,
  already-depended-on endpoint (M2's second ingestion route left the
  first unchanged; M6's population pipeline left both ingestion routes
  unchanged). See `docs/milestones/M7.md` §13.3.
- **Governance-health metrics are windowed (`?since=`, default 24h);
  system-health metrics are not.** An unbounded, all-time count over
  `verdicts`/`findings`/`population_findings` — tables with no retention
  policy, M11 not built — would get slower without limit for as long as
  the platform runs. Found during this milestone's own design-phase
  hostile-review pass, not in the original draft. See
  `docs/milestones/M7.md` §13.15.
- **`evidence_chain`'s size is read via a tail-row `ORDER BY
  sequence_number DESC LIMIT 1`, never `COUNT(*)`.** Postgres has no
  fast, O(1) row count under MVCC; `evidence_chain` is the one table in
  this schema that is permanent and never shrinks, making a `COUNT(*)`
  mistake here the most severe possible instance of it. The response
  field is named `evidence_chain_latest_sequence_number`, not
  `..._length`, specifically so its own name doesn't invite the mistake.
  See `docs/milestones/M7.md` §13.16.
- **Population-binding staleness is a `LEFT JOIN` anchored on `ACTIVE`
  `population_policy_bindings`, never an aggregate starting from
  `population_findings`.** A binding that has never once produced a
  finding — the single most important case this metric exists to catch —
  would otherwise be silently absent from the result instead of showing
  the loudest possible staleness signal (`None`). See
  `docs/milestones/M7.md` §13.17.
- **The readiness check reads a real table (`systems`), not a bare
  `SELECT 1`.** Found during this milestone's own post-implementation
  hostile review: a query touching no table proves connectivity and
  authentication but nothing about whether the running role's actual
  table-level grants are intact — a role that could log in but had every
  grant revoked would still report "reachable." See
  `docs/milestones/M7.md`'s production-readiness review.
- **A bounded database-connection timeout, found necessary while
  implementing the readiness check, not designed in advance.** Connecting
  to a genuinely unreachable host (a silently dropped route, not a fast
  "connection refused") could otherwise hang for the OS's full
  TCP-retransmission timeout — well over a minute, observed directly
  during this milestone's implementation. `db/session.create_db_engine`
  now bounds this for every consumer of the shared engine. See
  `docs/milestones/M7.md`'s production-readiness review.
- **No sandbox-timeout counter — reversed from this milestone's own
  first design draft.** A process-local, in-memory counter would silently
  produce wrong (undercounted, non-additive across replicas) numbers the
  moment this platform runs more than one worker/replica — the one
  metric in this design that would have broken the "computed from
  shared, durable Postgres state, therefore automatically correct under
  horizontal scaling" property every other metric here correctly has.
  `plugins/sandbox.py` remains completely untouched by M7. See
  `docs/milestones/M7.md` §13.11.
- **No authentication was added anywhere, including the two new M7
  endpoints** — consistent with every existing endpoint, but now a
  fourth consecutive milestone (M5, M6, M7) widening a gap every one of
  these reviews has flagged rather than solved. See
  `docs/milestones/M7.md` §13.10.

## M6-specific notes

- **"Async ingestion plane" is read as the async plane population-level
  policies specifically need — not a redesign of the two existing,
  synchronous per-event ingestion routes.** `POST /v1/ingestion/events`
  and `POST /v1/ingestion/events/credit-scorecard` are byte-for-byte
  unchanged: same request/response shape, same synchronous contract. This
  is the single highest-stakes reading call M6 makes — see
  `docs/milestones/M6.md` §13.1 for the full reasoning and the literal
  alternative reading this review declined.
- **The "Event Lake" is a new read pattern, not new storage.** `decision_events`
  (already normalized, already persisted by the unchanged ingestion path)
  is queried in a new, windowed, per-system way by
  `population_engine/window.py` — no new table, no new storage technology.
  See `docs/milestones/M6.md` §13.2.
- **Population-level policies are a new, third plugin port
  (`PopulationPolicy`), never a widened `Policy`.** `Policy.evaluate`'s
  single-event, `Finding`-per-`decision_event_id` contract is structurally
  incompatible with an aggregate result over many decisions — this is not
  a case of two similar things differing slightly, it's two genuinely
  different questions that happen to share the word "policy". See
  `docs/milestones/M6.md` §9/§13.3.
- **Population reads resolve `DIRECT`-ness against the DB-backed
  `protected_attribute_rules` (M5), not the static `classification.py`
  copy `DirectAttributeInInputsPolicy` uses** — the batch job already has
  full database access, so none of the constraints that forced that
  policy onto the static ruleset (M5 §13.9) apply here. See
  `docs/milestones/M6.md` §13.15.
- **A population finding is point-in-time reproducible, not a live view.**
  Because `protected_attribute_rules` is live, admin-mutable data with no
  versioning of its own (unlike `population_policy_version`, which already
  pins the policy's code identity), every `PopulationFinding` embeds
  exactly which classifications it was computed against
  (`classification_snapshot`) — found during this milestone's own
  hostile-review pass, not in the original design draft. `population_findings`
  is append-only at the database-privilege level for the identical reason.
  A "recompute under today's rules" capability is a distinct, deliberately
  unbuilt "what-if" feature. See `docs/milestones/M6.md` §13.16 — this
  review's most consequential correction.
- **Population Policy Bindings are `system_id`-keyed, not `adapter_id`-keyed.**
  A population-level analysis is naturally about a System's aggregate
  decisions across however many adapter versions have produced them over
  time — a new, separate key decision from `policy_bindings`' own
  `adapter_id` key, not a copy-paste of it. See
  `docs/milestones/M6.md` §13.8.
- **Windows are fixed, calendar-aligned, and closed in the past** —
  by default, "yesterday's full UTC day," never `[now() - 30d, now())`.
  Combined with `REPEATABLE READ` window-building reads and a `UNIQUE
  (population_policy_id, system_id, window_start, window_end)` constraint,
  a duplicate or overlapping `run_policies` invocation is a clean,
  detectable no-op, not a race producing two disagreeing findings for
  "the same" window — reversed from this milestone's own first design
  draft during the hostile-review pass. See `docs/milestones/M6.md` §13.13.
- **No authentication was added anywhere, including the two new M6 admin
  endpoints** — consistent with every existing admin endpoint, but
  flagged more sharply than M5's identical gap: `population_findings` is
  the first table in this platform whose entire content is a
  disparate-impact judgment about a real system, not just operational
  config. Named loudly, not solved piecemeal here — see
  `docs/milestones/M6.md` §13.14.

## M5-specific notes

- **Policy Bindings are keyed by `adapter_id`, not `System.domain`/
  jurisdiction — a deliberately narrower reading of "Policy Bindings" than
  the architecture's literal phrase.** The richer, domain/jurisdiction-keyed
  design would require resolving a `DecisionEvent`'s `System.domain`
  *before* `GovernanceEngine` can be constructed, a real ingestion-pipeline
  reorder — deferred until a second real domain exists to design it
  against (`FINANCE` is still the only one). See
  `docs/milestones/M5.md` §13.1 for the full reasoning; this is the single
  highest-stakes call M5 made.
- **Severity lives on `PolicyBinding`, not on `Policy`.** How serious a
  violation is *in the context of a specific adapter* is an administrative
  judgment, not a property of what the policy's code checks — the same
  separation of concerns that already moved `governing_policy_ids` off
  `Adapter` and into the database. `FindingOutcome` stays binary
  `CLEAR`/`FLAGGED`; escalation tier is derived from severity, never stored
  on `Finding`.
- **DB-backed protected-attribute rules apply to `EvidenceStore`'s
  resolution path only — `DirectAttributeInInputsPolicy` deliberately keeps
  reading the static, in-code ruleset.** Unifying both consumers would
  require giving a `Policy` — constructed with zero arguments everywhere in
  this codebase — real database access, a `Policy` port change M5
  intentionally does not make on top of everything else it already
  changes. A named, temporary divergence: an admin editing
  `protected_attribute_rules` changes what gets *persisted* as resolved,
  not what `DirectAttributeInInputsPolicy` *judges* as a leak, until a
  later milestone unifies the two. See `docs/milestones/M5.md` §13.9.
- **Evidence signing is a single static Ed25519 keypair, no KMS/HSM, no
  rotation.** `signing_key_id` travels with every signed record so a
  future rotation milestone can tell which key verifies which record
  without guessing. Real key custody is real infrastructure scope this
  platform has no second deployment environment to design correctly
  against yet — named explicitly, not silently deferred.
- **`VerdictStatus.ALLOW`/`FLAGGED` are permanent, historical-only enum
  members — no data migration of M0–M4 verdicts.** A `Verdict`'s `status`
  is embedded in the hash-chained, immutable `evidence_chain.payload`;
  rewriting the separate, mutable `verdicts.status` column for historical
  rows would make the queryable view disagree with the evidence-of-record
  for the same event. No M5+ code path ever constructs a new
  `GovernanceVerdict` with either legacy value.
- **No authentication was added anywhere, including the two new M5 admin
  endpoints** — consistent with every existing admin endpoint, but flagged
  because Policy Bindings materially raise the stakes of that gap: an
  unauthenticated deactivate call can now silently stop a policy from
  governing real financial decisions. Named loudly in the M5
  production-readiness review, not solved piecemeal here.

## M4-specific notes

- **`governing_policy_ids` is a static, code-defined tuple — not a
  preview of M5's Policy Bindings.** An adapter still declares which
  policy families govern it at class-definition time, the same as M2/M3's
  singular `governing_policy_id`; M4 only widens the type from one string
  to a tuple of strings. Making this database-configurable per-System, at
  runtime, without a redeploy, is exactly the problem M5's Policy Bindings
  exist to solve — M4 deliberately does not reach for it early.
- **Plurality is OR-of-`FLAGGED`, evaluated independently per policy
  family.** `GovernanceEngine.govern` runs every `Policy` in its
  constructor-supplied list and flags the whole `Verdict` if any one of
  them flags — there is no weighting, precedence, or partial-credit
  model, and a policy that raises fails the entire request rather than
  degrading to a partial verdict (`governance_engine/engine.py`'s
  docstring explains why: a silently-dropped Finding is a worse failure
  mode than a loud 500).
- **Shadow execution and policy plurality are orthogonal, by design.**
  A `SHADOW`-state policy for one governing family has zero effect on
  the other families' findings or on the aggregate `Verdict` — each
  family's `PRODUCTION`/`SHADOW` resolution happens independently inside
  the ingestion route, and only `PRODUCTION` policies are ever passed to
  `GovernanceEngine`. See
  `test_shadow_candidate_for_one_family_does_not_affect_the_other_familys_finding`
  in `tests/integration/test_shadow_execution_postgres.py`.
- **The `credit-scorecard` version bump (`0.1.0` → `0.2.0`) is the
  worked example of the M3 lifecycle mechanism doing real work, not just
  passing tests.** Registering `0.2.0` as `PRODUCTION` auto-demotes
  `0.1.0` to `SHADOW` via the database's partial unique index — verified
  live against the real containerized Postgres (not just the test suite)
  by seeding the registry and querying `plugin_registrations` directly.
  The version bump itself follows the same rule M3 established: a
  behavior change to what a versioned plugin identity means is a new
  version registered through the lifecycle, never a silent mutation of
  what `0.1.0` meant while it was `PRODUCTION`.

## M3-specific notes

- **Route existence vs. route behavior — two different DB-dependency
  rules, deliberately.** `api/ingestion/routes.py`'s
  `build_ingestion_router()` generates routes from the **in-process**
  plugin registry only (`plugins.bootstrap`'s imports) — zero database
  access, preserving the invariant every milestone since M0 has relied on
  (`create_app()` needs no live database). Which policy actually governs
  a given request (`PRODUCTION` vs `SHADOW`) is resolved **fresh from the
  database on every request**, inside the generated handler — so
  promoting/demoting a plugin via the Admin API takes effect on the very
  next request, no restart needed. Don't conflate the two: a route can
  exist and still reject traffic with a `503` if its adapter or policy
  isn't actually `PRODUCTION` yet.
- **A never-registered adapter and an explicit `DRAFT` registration are
  rejected identically.** Both mean "not accepting production traffic
  yet" from the caller's perspective — a `503`, not a `404` (the route
  itself genuinely exists; it's just not live).
- **Adapter-level `SHADOW` has no distinct meaning from `PRODUCTION` yet.**
  Both fully process and persist real traffic identically. The
  meaningful `SHADOW` distinction M3 actually delivers is for
  **policies** — evaluated against real traffic, persisted to
  `shadow_findings`, never affecting the served Verdict. Extending
  shadow semantics to adapters (e.g., processing real traffic without
  committing evidence) is a reasonable future enhancement, not built now.
- **Sandboxing is a soft timeout + exception isolation, not process/
  container isolation** — a deliberate scope decision (see
  `docs/milestones/M3.md` §13.1), because there is no untrusted
  third-party plugin author yet. A plugin that hangs forever still
  consumes a background thread forever; the caller just stops waiting
  for it. Read `plugins/sandbox.py`'s docstring before assuming this
  provides security isolation — it does not.
- **`create`/`promote` on the plugin registry translate a real database
  race into a clean `ValueError`, but not symmetrically with the Admin
  API's own pre-checks** — see `docs/milestones/M3.md`'s production-
  readiness review for the accepted `409` vs `422` inconsistency this
  leaves, and why the `promote()` race specifically has no direct test
  (a genuine two-thread test was attempted and found to assert a false
  invariant under low contention).

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
