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

M3 adds three identity class attributes — `adapter_id`, `version`,
`governing_policy_ids` — mirroring `Policy`'s existing `policy_id`/`version`.
`translate`'s signature is completely unchanged; this is metadata *about*
an adapter, not a new capability *of* one:

* `adapter_id`/`version` let `plugins.registry` catalog this
  implementation and let the M3 registry track its lifecycle state
  (draft/shadow/production) without any code change to this class.
* `governing_policy_ids` names which `Policy.policy_id` families decide
  `FLAGGED`/`CLEAR` for events this adapter produces. This exists because
  `Policy.evaluate(event) -> Finding` deliberately has no database access
  (see `docs/milestones/M3.md` §9) and so cannot look up which policies
  should govern a given event dynamically — the association has to live
  somewhere static, and the adapter (which already encodes "this is a
  FINANCE-domain credit scorecard," for example) is the natural place for
  it, not a new binding table (that richer "which policy for which
  domain/jurisdiction" concept is explicitly M5's Policy Bindings, not
  this).

  M4 widens this from a single id (M3) to a tuple: `GovernanceEngine`
  now runs every policy family an adapter declares and aggregates their
  Findings (architecture §8, "policy plurality" — see
  `docs/milestones/M4.md`). Still a fixed, code-defined tuple, not
  admin-configurable — *dynamically* binding policies to domains/
  jurisdictions remains M5's Policy Bindings, not this (see
  `docs/milestones/M4.md` §13.1 for why conflating the two would be a
  real scope-creep mistake, not a simplification).
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
    governing_policy_ids: tuple[str, ...]

    @abstractmethod
    def translate(self, raw_payload: TPayload) -> DecisionEvent:
        """Translate one native payload into one canonical Decision Event.

        Implementations must not perform normalization (see
        `normalization.service.NormalizationService`) or policy evaluation —
        an adapter's single responsibility is field-level translation.
        """
        raise NotImplementedError
