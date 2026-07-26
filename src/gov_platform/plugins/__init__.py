"""Plugin infrastructure — architecture §6, M3.

Two deliberately separate concerns live under this package:

* `registry.py` — the in-process catalog of which `Adapter`/`Policy`
  *implementations this deployed codebase's own Python code knows how to
  run at all*. Populated by decorators at import time; no database, no
  dynamic loading of code from outside this codebase (see
  `docs/milestones/M3.md` §13.2).
* `sandbox.py` — the timeout + exception isolation every registry-
  dispatched plugin call runs under (§13.1: deliberately not process- or
  container-level isolation — there is no untrusted third-party plugin
  author yet).

*Lifecycle state* (draft/shadow/production) is a separate, database-backed
fact — see `schemas/plugin_registration.py` and
`db/repositories/plugin_registration.py` — answering "which of the
implementations this process knows about is currently trusted to run?"
rather than "what implementations exist?".
"""
