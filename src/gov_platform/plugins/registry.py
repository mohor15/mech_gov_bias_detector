"""The in-process plugin registry — architecture §6, M3.

Answers exactly one question: "what `Adapter`/`Policy` implementations
does this deployed codebase's own Python code know how to run?" —
populated by the `@register_adapter`/`@register_policy` decorators, which
run as an ordinary side effect of importing a module, the same way a
class always exists the moment its defining module is imported. This is
*not* dynamic or external plugin loading (see `docs/milestones/M3.md`
§13.2): the only modules ever queried here are the ones `plugins.bootstrap`
explicitly imports, which are ordinary first-party modules in this
codebase, reviewed and deployed the normal way.

Deliberately separate from *lifecycle state* (draft/shadow/production),
which is a database fact an admin controls at runtime without a redeploy
— see `db/repositories/plugin_registration.py`. This module only ever
answers "does an implementation for this id/version exist in this
process?", never "is it currently trusted to run?".

M6: `register_population_policy`/`get_population_policy_class`/
`known_population_policy_keys` extend the exact same mechanism to
`PopulationPolicy` (`population_engine/base.py`) — the third plugin kind,
no second registry invented. See `docs/milestones/M6.md` §13.7.
"""

from __future__ import annotations

from typing import Any

from gov_platform.adapters.base import Adapter
from gov_platform.policy_engine.base import Policy
from gov_platform.population_engine.base import PopulationPolicy

_AdapterClass = type[Adapter[Any]]
_PolicyClass = type[Policy]
_PopulationPolicyClass = type[PopulationPolicy]

_adapters: dict[tuple[str, str], _AdapterClass] = {}
_policies: dict[tuple[str, str], _PolicyClass] = {}
_population_policies: dict[tuple[str, str], _PopulationPolicyClass] = {}


def register_adapter(adapter_cls: _AdapterClass) -> _AdapterClass:
    """Class decorator: catalogs `adapter_cls` under its own
    `(adapter_id, version)`. Returns the class unchanged."""
    _adapters[(adapter_cls.adapter_id, adapter_cls.version)] = adapter_cls
    return adapter_cls


def register_policy(policy_cls: _PolicyClass) -> _PolicyClass:
    """Class decorator: catalogs `policy_cls` under its own
    `(policy_id, version)`. Returns the class unchanged."""
    _policies[(policy_cls.policy_id, policy_cls.version)] = policy_cls
    return policy_cls


def register_population_policy(
    population_policy_cls: _PopulationPolicyClass,
) -> _PopulationPolicyClass:
    """Class decorator: catalogs `population_policy_cls` under its own
    `(population_policy_id, version)`. Returns the class unchanged."""
    _population_policies[
        (population_policy_cls.population_policy_id, population_policy_cls.version)
    ] = population_policy_cls
    return population_policy_cls


def get_adapter_class(plugin_id: str, version: str) -> _AdapterClass | None:
    return _adapters.get((plugin_id, version))


def get_policy_class(plugin_id: str, version: str) -> _PolicyClass | None:
    return _policies.get((plugin_id, version))


def get_population_policy_class(plugin_id: str, version: str) -> _PopulationPolicyClass | None:
    return _population_policies.get((plugin_id, version))


def known_adapter_keys() -> frozenset[tuple[str, str]]:
    """Every `(adapter_id, version)` this process has registered —
    the set `plugins.seed_registry` and route generation both iterate."""
    return frozenset(_adapters)


def known_policy_keys() -> frozenset[tuple[str, str]]:
    return frozenset(_policies)


def known_population_policy_keys() -> frozenset[tuple[str, str]]:
    return frozenset(_population_policies)


def unregister_adapter(adapter_id: str, version: str) -> None:
    """Test-only escape hatch. Real plugins are never unregistered at
    runtime — there is no such code path, and no need for one: this
    module tracks *what code exists*, which never becomes false once a
    class is deployed (see this module's docstring; *lifecycle state* is
    the thing that changes, and that's a database concern, not this
    module's). This exists purely so a test registering a disposable fake
    plugin can clean up after itself, instead of leaking it into every
    other test's route generation for the rest of the session."""
    _adapters.pop((adapter_id, version), None)


def unregister_policy(policy_id: str, version: str) -> None:
    _policies.pop((policy_id, version), None)


def unregister_population_policy(population_policy_id: str, version: str) -> None:
    _population_policies.pop((population_policy_id, version), None)
