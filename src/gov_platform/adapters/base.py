"""The Adapter port.

An `Adapter` is the only thing in the platform allowed to know a source
system's native wire format. Everything downstream (normalization, policy
evaluation, governance, audit) only ever sees a canonical `DecisionEvent` —
this is what "domain-agnostic" and "model-agnostic" (architecture P3) mean
in code, not just in the diagram.

`abc.ABC` is used deliberately over `typing.Protocol` here: an explicit,
inherited contract is easier to discover ("what do I need to implement to
add a new source system?") than a structurally-typed one, which matters for
a plugin surface other teams will extend from M3 onward.

`Adapter` is generic over its payload type (`Adapter[TPayload]`) rather than
typing `translate` as `Any`. Each concrete adapter fixes its own wire-format
type (e.g. `Adapter[SyntheticSourcePayload]`), so callers holding a
concretely-parameterized `Adapter` get real type checking on `translate`
instead of an abstraction that accepts anything. This was tightened during
the M0 finalization review — see the production-readiness review for
rationale — and costs nothing extra for M3's future adapters, each of which
will parameterize `Adapter` with its own payload type the same way.

M3 added two identity class attributes — `adapter_id`, `version` —
mirroring `Policy`'s own `policy_id`/`version`. `translate`'s signature is
completely unchanged; this is metadata *about* an adapter, not a new
capability *of* one. They let `plugins.registry` catalog this
implementation and let the M3 registry track its lifecycle state
(draft/shadow/production) without any code change to this class.

M3/M4 also carried a `governing_policy_ids` class attribute here — a fixed,
code-defined tuple naming which `Policy.policy_id` families governed this
adapter's events, since `Policy.evaluate(event) -> Finding` has no database
access and so cannot look up which policies should govern a given event
dynamically. M5 removes it entirely: which policies govern an adapter is
now a database fact (`schemas/policy_binding.py`'s `PolicyBinding`,
keyed by `adapter_id`), administered via the Admin API without a redeploy
— see `docs/milestones/M5.md` §13.1/§13.3. `plugins/seed_registry.py` seeds
the equivalent bindings for both first-party adapters, so this is a pure
storage-location change, not a behavior change, for existing traffic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from gov_platform.schemas.decision_event import DecisionEvent

TPayload = TypeVar("TPayload")


class Adapter(ABC, Generic[TPayload]):
    """Translates a source system's native payload into a `DecisionEvent`."""

    adapter_id: str
    version: str

    @abstractmethod
    def translate(self, raw_payload: TPayload) -> DecisionEvent:
        """Translate one native payload into one canonical Decision Event.

        Implementations must not perform normalization (see
        `normalization.service.NormalizationService`) or policy evaluation —
        an adapter's single responsibility is field-level translation.
        """
        raise NotImplementedError
