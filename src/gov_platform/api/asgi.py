"""ASGI entrypoint: `uvicorn gov_platform.api.asgi:app`.

Deliberately separate from `api.app` (the factory module). `create_app()`
has a side effect — it touches the filesystem to open the Evidence Store's
SQLite file — so it must not run merely because something imported
`api.app` to get at `create_app` itself (as every test in this repository
does). Only this module, which nothing else imports, constructs the
default, environment-configured instance.
"""

from __future__ import annotations

from gov_platform.api.app import create_app

app = create_app()
