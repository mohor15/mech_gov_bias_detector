"use strict";

// Plain fetch() + DOM manipulation only -- no framework, no templating
// helper, no build step (docs/milestones/M10.md §4.1/§8.2). Every value
// that ever originates from an API response is inserted via textContent
// (never innerHTML string-concatenation) -- a blanket rule with no
// exception list, because there is no closed, enumerable set of "the
// risky fields" in a platform where every write endpoint is
// unauthenticated (M10.md §4.3/§6).

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function textNode(value) {
  return document.createTextNode(value === null || value === undefined ? "" : String(value));
}

function cell(tag, value) {
  const node = document.createElement(tag);
  node.appendChild(textNode(value));
  return node;
}

function paragraph(value) {
  return cell("p", value);
}

function heading(level, value) {
  return cell("h" + level, value);
}

function errorBanner(message) {
  const node = document.createElement("p");
  node.className = "dashboard-error";
  node.appendChild(textNode(message));
  return node;
}

function emptyNotice(label) {
  return paragraph("No " + label + " to show.");
}

function fetchJson(url) {
  return fetch(url).then((response) => {
    if (!response.ok) {
      throw new Error(url + " returned HTTP " + response.status);
    }
    return response.json();
  });
}

function buildTable(headers, rows) {
  const table = document.createElement("table");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => headRow.appendChild(cell("th", header)));
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((value) => tr.appendChild(cell("td", value)));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  return table;
}

// --- Overview (`/dashboard`) -------------------------------------------
//
// Renders `GET /v1/admin/metrics` and `GET /readyz` side by side. These
// are two independent requests, not one atomic snapshot -- the database
// can change state between them. That is an inherent property of
// composing a page from independent fetch() calls with no client-side
// consistency mechanism available, not a defect this view can fix on its
// own (see the M10 hostile-review discussion of this same tension).

function renderOverview(container) {
  clearNode(container);
  const section = document.createElement("section");
  section.className = "dashboard-section";
  container.appendChild(section);

  Promise.all([
    fetchJson("/v1/admin/metrics"),
    fetch("/readyz").then((response) => ({ ok: response.ok, status: response.status })),
  ])
    .then(([metrics, readiness]) => {
      clearNode(section);
      section.appendChild(
        paragraph(
          "Readiness: " + (readiness.ok ? "READY" : "NOT READY (HTTP " + readiness.status + ")")
        )
      );
      section.appendChild(paragraph("Database reachable: " + metrics.system.db_reachable));
      section.appendChild(
        paragraph(
          "Database latency (ms): " +
            (metrics.system.db_latency_ms === null ? "n/a" : metrics.system.db_latency_ms)
        )
      );
      section.appendChild(
        paragraph(
          "Evidence chain tail sequence: " +
            metrics.system.evidence_chain_latest_sequence_number
        )
      );

      container.appendChild(
        heading(
          2,
          "Governance health (" +
            metrics.governance.window_start +
            " to " +
            metrics.governance.window_end +
            ")"
        )
      );
      const verdictRows = Object.keys(metrics.governance.verdict_counts_by_status).map(
        (status) => [status, metrics.governance.verdict_counts_by_status[status]]
      );
      container.appendChild(
        verdictRows.length === 0
          ? emptyNotice("verdicts in this window")
          : buildTable(["Verdict status", "Count"], verdictRows)
      );
    })
    .catch((error) => {
      clearNode(section);
      section.appendChild(errorBanner("Could not load system/governance health: " + error.message));
    });
}

// --- Population Findings (`/dashboard/population-findings`) ------------

function renderPopulationFindings(container) {
  clearNode(container);

  const filterSection = document.createElement("div");
  filterSection.className = "dashboard-filters";
  const label = document.createElement("label");
  label.appendChild(textNode("System: "));
  const select = document.createElement("select");
  select.appendChild(new Option("All systems", ""));
  label.appendChild(select);
  filterSection.appendChild(label);
  container.appendChild(filterSection);

  const resultsSection = document.createElement("div");
  container.appendChild(resultsSection);

  function loadFindings(systemId) {
    clearNode(resultsSection);
    const url =
      "/v1/admin/population-findings" +
      (systemId ? "?system_id=" + encodeURIComponent(systemId) : "");
    fetchJson(url)
      .then((findings) => {
        const rows = findings.map((finding) => [
          finding.id,
          finding.system_id,
          finding.population_policy_id,
          finding.outcome,
          finding.window_start,
          finding.window_end,
          finding.evaluated_at,
          finding.rationale,
        ]);
        resultsSection.appendChild(
          rows.length === 0
            ? emptyNotice("population findings")
            : buildTable(
                [
                  "ID",
                  "System",
                  "Policy",
                  "Outcome",
                  "Window start",
                  "Window end",
                  "Evaluated at",
                  "Rationale",
                ],
                rows
              )
        );
      })
      .catch((error) => {
        resultsSection.appendChild(
          errorBanner("Could not load population findings: " + error.message)
        );
      });
  }

  fetchJson("/v1/admin/systems")
    .then((systems) => {
      systems.forEach((system) => select.appendChild(new Option(system.name, system.id)));
    })
    .catch((error) => {
      filterSection.appendChild(
        errorBanner("Could not load the system list for filtering: " + error.message)
      );
    });

  select.addEventListener("change", () => loadFindings(select.value));
  loadFindings("");
}

// --- Review Queue (`/dashboard/reviews`) --------------------------------

function buildStatusFilter() {
  const select = document.createElement("select");
  ["", "OPEN", "IN_REVIEW", "RESOLVED"].forEach((value) =>
    select.appendChild(new Option(value === "" ? "All" : value, value))
  );
  return select;
}

function renderReviews(container) {
  clearNode(container);

  // Verdict reviews.
  const verdictSection = document.createElement("section");
  verdictSection.className = "dashboard-section";
  verdictSection.appendChild(heading(2, "Verdict Reviews"));

  const verdictFilters = document.createElement("div");
  verdictFilters.className = "dashboard-filters";

  const statusLabel = document.createElement("label");
  statusLabel.appendChild(textNode("Status: "));
  const statusSelect = buildStatusFilter();
  statusLabel.appendChild(statusSelect);
  verdictFilters.appendChild(statusLabel);

  const severityLabel = document.createElement("label");
  severityLabel.appendChild(textNode("Severity: "));
  const severitySelect = document.createElement("select");
  ["", "ESCALATE_FOR_REVIEW", "RECOMMEND_HOLD"].forEach((value) =>
    severitySelect.appendChild(new Option(value === "" ? "All" : value, value))
  );
  severityLabel.appendChild(severitySelect);
  verdictFilters.appendChild(severityLabel);

  verdictSection.appendChild(verdictFilters);
  const verdictResults = document.createElement("div");
  verdictSection.appendChild(verdictResults);
  container.appendChild(verdictSection);

  function loadVerdictReviews() {
    clearNode(verdictResults);
    const params = [];
    if (statusSelect.value) params.push("status=" + encodeURIComponent(statusSelect.value));
    if (severitySelect.value) params.push("severity=" + encodeURIComponent(severitySelect.value));
    const url = "/v1/admin/verdict-reviews" + (params.length ? "?" + params.join("&") : "");
    fetchJson(url)
      .then((reviews) => {
        const rows = reviews.map((review) => [
          review.id,
          review.verdict.status,
          review.status,
          review.reviewer,
          review.resolution,
          review.resolution_notes,
          review.created_at,
        ]);
        verdictResults.appendChild(
          rows.length === 0
            ? emptyNotice("verdict reviews")
            : buildTable(
                [
                  "ID",
                  "Verdict status",
                  "Review status",
                  "Reviewer",
                  "Resolution",
                  "Notes",
                  "Created at",
                ],
                rows
              )
        );
      })
      .catch((error) => {
        verdictResults.appendChild(
          errorBanner("Could not load verdict reviews: " + error.message)
        );
      });
  }

  statusSelect.addEventListener("change", loadVerdictReviews);
  severitySelect.addEventListener("change", loadVerdictReviews);
  loadVerdictReviews();

  // Population finding reviews.
  const findingSection = document.createElement("section");
  findingSection.className = "dashboard-section";
  findingSection.appendChild(heading(2, "Population Finding Reviews"));

  const findingFilters = document.createElement("div");
  findingFilters.className = "dashboard-filters";
  const findingStatusLabel = document.createElement("label");
  findingStatusLabel.appendChild(textNode("Status: "));
  const findingStatusSelect = buildStatusFilter();
  findingStatusLabel.appendChild(findingStatusSelect);
  findingFilters.appendChild(findingStatusLabel);
  findingSection.appendChild(findingFilters);

  const findingResults = document.createElement("div");
  findingSection.appendChild(findingResults);
  container.appendChild(findingSection);

  function loadFindingReviews() {
    clearNode(findingResults);
    const url =
      "/v1/admin/population-finding-reviews" +
      (findingStatusSelect.value ? "?status=" + encodeURIComponent(findingStatusSelect.value) : "");
    fetchJson(url)
      .then((reviews) => {
        const rows = reviews.map((review) => [
          review.id,
          review.population_finding.outcome,
          review.status,
          review.reviewer,
          review.resolution,
          review.resolution_notes,
          review.created_at,
        ]);
        findingResults.appendChild(
          rows.length === 0
            ? emptyNotice("population finding reviews")
            : buildTable(
                [
                  "ID",
                  "Finding outcome",
                  "Review status",
                  "Reviewer",
                  "Resolution",
                  "Notes",
                  "Created at",
                ],
                rows
              )
        );
      })
      .catch((error) => {
        findingResults.appendChild(
          errorBanner("Could not load population finding reviews: " + error.message)
        );
      });
  }

  findingStatusSelect.addEventListener("change", loadFindingReviews);
  loadFindingReviews();
}

// --- Routing -------------------------------------------------------------
//
// One shared shell (index.html) is served for all three dashboard routes;
// this client-side router decides what to render based on the current
// path, the "thin server, client renders" split M10.md §4.3 describes.

function renderCurrentView() {
  const container = document.getElementById("dashboard-content");
  const path = window.location.pathname;
  if (path === "/dashboard/population-findings") {
    renderPopulationFindings(container);
  } else if (path === "/dashboard/reviews") {
    renderReviews(container);
  } else {
    renderOverview(container);
  }
}

document.addEventListener("DOMContentLoaded", renderCurrentView);
