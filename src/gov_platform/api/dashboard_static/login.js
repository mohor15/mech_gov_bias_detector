"use strict";

// Plain fetch() + DOM manipulation only -- no framework, no templating
// helper, no build step, matching dashboard.js's own precedent
// (docs/milestones/M10.md §4.1/§8.2, extended to authentication by
// docs/milestones/M13.md §5.5). A single field, a submit handler that
// POSTs the token to /v1/auth/session, and an honest, visible error
// state on failure -- never a silent blank page.

function textNode(value) {
  return document.createTextNode(value === null || value === undefined ? "" : String(value));
}

function showError(message) {
  const errorContainer = document.getElementById("login-error");
  errorContainer.textContent = "";
  const node = document.createElement("p");
  node.className = "dashboard-error";
  node.appendChild(textNode(message));
  errorContainer.appendChild(node);
}

function handleSubmit(event) {
  event.preventDefault();
  const token = document.getElementById("login-token").value;

  fetch("/v1/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token }),
  }).then((response) => {
    if (response.ok) {
      window.location.href = "/dashboard";
      return;
    }
    showError(
      response.status === 401
        ? "That token is invalid or has been revoked."
        : "Could not sign in (HTTP " + response.status + ")."
    );
  }).catch((error) => {
    showError("Could not reach the server: " + error.message);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("login-form").addEventListener("submit", handleSubmit);
});
