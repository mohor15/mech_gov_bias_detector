"""CLI: generate a periodic, document-shaped compliance report for a
bounded, closed historical window — architecture §14, M12.

Mirrors `population_engine/run_policies.py`'s and
`retention/purge_expired_records.py`'s existing shape exactly: no daemon,
no in-process scheduler. Real scheduling (cron, a Kubernetes `CronJob`)
remains deployment-topology scope, architecture §17/M13, unchanged.

Default window is the last full calendar month (UTC) — the direct scaling
of `run_policies.py`'s own `default_window()` ("yesterday's full UTC day")
to a monthly cadence, matching the one concrete cadence this platform's
entire citation trail actually names ("a *monthly* compliance PDF," M10
§3.4). `--window-start`/`--window-end` override this, taken together or
not at all — the identical argument-pairing validation `run_policies.py`'s
own `main()` already enforces.

No call to `bootstrap_plugins()` — unlike `run_policies.py`, this tool
touches no `Adapter`/`Policy`/`PopulationPolicy` at all; it reads five
already-persisted tables directly. No `Settings` fields are read at all —
`--database-url` is the same explicit-argument convention every CLI in
this codebase already uses.

The connection built from `--database-url` uses `db.session.create_db_engine`,
not a bare `create_engine` — the same constructor every CLI in this
codebase except `db/migrate.py` already uses, and the one that carries the
`with_psycopg_driver` normalization added after a real CI failure during
M11 (`ModuleNotFoundError: No module named 'psycopg2'`, from a bare
`postgresql://` URL reaching a bare `create_engine` unnormalized — see
`db/session.py`'s own module docstring). No elevated database credential is
needed: every query `compliance_report.get_compliance_report` issues is a
`SELECT`, and `gov_platform_app` already holds `SELECT` on all five tables
this milestone reads.

Export formats: JSON (primary, complete, structured) and CSV (flattened,
opt-in, five files) — no PDF (see `docs/milestones/M12.md` §12.1, the
document's own highest-stakes call, resolved in favor of the stdlib
`json`/`csv` modules already relied on elsewhere in this codebase). CSV
produces exactly five files, one per genuinely flat table in the model —
`ReviewOutcomeCounts` holds two independently-keyed dicts
(`verdict_reviews_by_resolution`/`population_finding_reviews_by_resolution`),
so it maps to two files, not one (§5.5's corrected, final file list).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from gov_platform.audit.hash_chain import canonical_json
from gov_platform.db.session import create_db_engine
from gov_platform.reporting.compliance_report import ComplianceReport, get_compliance_report


def default_window(as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """The last full calendar month (UTC), relative to `as_of` (defaults to
    `datetime.now(UTC)`) — fixed, calendar-aligned, closed in the past.
    `as_of` is a seam for tests, not a CLI argument: real invocations
    always mean "as of right now"."""
    now = as_of or datetime.now(UTC)
    window_end = datetime(now.year, now.month, 1, tzinfo=UTC)
    if now.month == 1:
        window_start = datetime(now.year - 1, 12, 1, tzinfo=UTC)
    else:
        window_start = datetime(now.year, now.month - 1, 1, tzinfo=UTC)
    return window_start, window_end


def _flat_rows(counts: dict[str, int]) -> list[tuple[str, int]]:
    """Deterministic row order for CSV output -- `GROUP BY` carries no
    `ORDER BY`, so sorting here is what makes two exports of the identical
    report byte-identical, the same guarantee `canonical_json`'s
    `sort_keys=True` gives the JSON export."""
    return sorted(counts.items())


def _nested_flat_rows(counts: dict[str, dict[str, int]]) -> list[tuple[str, str, int]]:
    return [
        (outer_key, inner_key, counts[outer_key][inner_key])
        for outer_key in sorted(counts)
        for inner_key in sorted(counts[outer_key])
    ]


def _write_csv(path: Path, header: list[str], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_csv_files(report: ComplianceReport, output_prefix: str) -> list[Path]:
    """Five files, one per genuinely flat table in the model -- the
    corrected, final file list (`docs/milestones/M12.md` §5.5). Returns
    the paths written, in the same order they're written."""
    targets: list[tuple[Path, list[str], list[tuple[object, ...]]]] = [
        (
            Path(f"{output_prefix}-verdicts.csv"),
            ["status", "count"],
            list(_flat_rows(report.verdicts.by_status)),
        ),
        (
            Path(f"{output_prefix}-findings.csv"),
            ["policy_id", "outcome", "count"],
            list(_nested_flat_rows(report.findings.by_policy)),
        ),
        (
            Path(f"{output_prefix}-population-findings.csv"),
            ["population_policy_id", "outcome", "count"],
            list(_nested_flat_rows(report.population_findings.by_policy)),
        ),
        (
            Path(f"{output_prefix}-verdict-reviews.csv"),
            ["resolution", "count"],
            list(_flat_rows(report.reviews.verdict_reviews_by_resolution)),
        ),
        (
            Path(f"{output_prefix}-population-finding-reviews.csv"),
            ["resolution", "count"],
            list(_flat_rows(report.reviews.population_finding_reviews_by_resolution)),
        ),
    ]
    for path, header, rows in targets:
        _write_csv(path, header, rows)
    return [path for path, _, _ in targets]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a compliance summary report -- verdict/finding/population-finding "
            "counts and Human Review Workflow resolution outcomes -- for a bounded, closed "
            "historical window. Defaults to the last full calendar month (UTC)."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="The app's own runtime connection (e.g. GOV_PLATFORM_DATABASE_URL) -- every "
        "query is a read-only SELECT, no elevated credential needed.",
    )
    parser.add_argument("--window-start", required=False, help="ISO 8601 UTC timestamp, inclusive.")
    parser.add_argument("--window-end", required=False, help="ISO 8601 UTC timestamp, exclusive.")
    parser.add_argument(
        "--system-id", required=False, help="Omit for a platform-wide report (every system)."
    )
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument(
        "--output",
        required=False,
        help="--format json: a file path (omit for stdout). --format csv: a required path "
        "prefix -- five files are written, <prefix>-verdicts.csv etc.",
    )
    args = parser.parse_args(argv)

    if bool(args.window_start) != bool(args.window_end):
        parser.error("--window-start and --window-end must be given together, or not at all")

    if args.format == "csv" and not args.output:
        parser.error("--format csv requires --output (used as a path prefix)")

    if args.window_start and args.window_end:
        window_start = datetime.fromisoformat(args.window_start)
        window_end = datetime.fromisoformat(args.window_end)
    else:
        window_start, window_end = default_window()

    engine = create_db_engine(args.database_url)
    report = get_compliance_report(
        engine, window_start=window_start, window_end=window_end, system_id=args.system_id
    )

    if args.format == "json":
        text = canonical_json(report.model_dump(mode="json"))
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"WROTE {args.output}")
        else:
            print(text)
    else:
        for path in write_csv_files(report, args.output):
            print(f"WROTE {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
