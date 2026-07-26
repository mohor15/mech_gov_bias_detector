"""CLI: idempotently register every first-party plugin `plugins.bootstrap`
knows about and promote each straight to `PRODUCTION` — architecture §6,
M3.

Not something `create_app()` does itself: `create_app()` must stay
DB-free at construction time (an invariant every milestone since M0 has
preserved — see `api/app.py`'s module docstring), so seeding the registry
is a separate, explicit ops step, the same relationship `db.migrate` has
to schema. Run once after applying migrations, before the app is expected
to serve real ingestion traffic. Safe to re-run: an already-`PRODUCTION`
registration is left alone, not re-promoted or duplicated.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.session import create_db_engine
from gov_platform.plugins.bootstrap import bootstrap_plugins
from gov_platform.plugins.registry import known_adapter_keys, known_policy_keys
from gov_platform.schemas.plugin_registration import PluginLifecycleState, PluginType


def seed_to_production(
    session: Session,
    repository: PluginRegistrationRepository,
    *,
    plugin_type: PluginType,
    plugin_id: str,
    version: str,
) -> str:
    """Ensure `(plugin_type, plugin_id, version)` is registered and at
    `PRODUCTION`. Returns a short, human-readable status line."""
    registration = repository.get_by_identity(
        session, plugin_type=plugin_type, plugin_id=plugin_id, version=version
    )
    if registration is None:
        registration = repository.create(
            session, plugin_type=plugin_type, plugin_id=plugin_id, version=version
        )

    # Captured as a plain bool, not an early `return`: an early return here
    # would let mypy narrow `registration.lifecycle_state`'s type to
    # exclude PRODUCTION for the rest of this function, making the loop
    # condition below look like an always-true comparison to it -- even
    # though `registration` is reassigned every iteration to a fresh
    # object whose state genuinely can reach PRODUCTION.
    was_already_production = registration.lifecycle_state is PluginLifecycleState.PRODUCTION

    while registration.lifecycle_state is not PluginLifecycleState.PRODUCTION:
        registration = repository.promote(session, registration.id)

    if was_already_production:
        return f"{plugin_type.value} {plugin_id} {version}: already PRODUCTION"
    return f"{plugin_type.value} {plugin_id} {version}: promoted to PRODUCTION"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the plugin registry to PRODUCTION.")
    parser.add_argument("--database-url", required=True, help="The app's own runtime connection")
    args = parser.parse_args(argv)

    bootstrap_plugins()
    engine = create_db_engine(args.database_url)
    repository = PluginRegistrationRepository()

    with Session(engine) as session:
        results = [
            seed_to_production(
                session,
                repository,
                plugin_type=PluginType.ADAPTER,
                plugin_id=plugin_id,
                version=version,
            )
            for plugin_id, version in sorted(known_adapter_keys())
        ]
        results += [
            seed_to_production(
                session,
                repository,
                plugin_type=PluginType.POLICY,
                plugin_id=plugin_id,
                version=version,
            )
            for plugin_id, version in sorted(known_policy_keys())
        ]
        session.commit()

    for line in results:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
