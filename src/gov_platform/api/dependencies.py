"""FastAPI dependency providers.

Route handlers depend on these functions, never on concrete singletons
imported at module scope — this is what makes `api.app.create_app` a real
composition root and lets tests override any collaborator (e.g. pointing
the Evidence Store at a temp file) without monkeypatching module globals,
the trap V1 fell into with its bare module-level `pipeline = MechGovPipeline()`.

`NormalizationService` and `EvidenceStore` stay typed as concrete classes
deliberately: the architecture never defines them as swappable plugin
surfaces (only `Adapter` and `Policy` are ports), so introducing an
abstraction for them here would be speculative, not a fix.

M3 removes `get_adapter`/`get_credit_scorecard_adapter`/
`get_governance_engine`/`get_credit_scorecard_governance_engine` — M2's
per-adapter providers are obsolete now that ingestion routes are generated
from the plugin registry (see `api/ingestion/routes.py`): each generated
route's handler closes directly over its own adapter instance and resolves
its governing policy per-request from the database, rather than going
through a named provider function per adapter (there would need to be one
such function per registered adapter, which is exactly the "modifying the
composition root for every new adapter" problem M3 exists to remove).
`get_plugin_registration_repository` and `get_shadow_finding_repository`
are new — needed by both the Admin Plugins API and the generated ingestion
routes' per-request policy-lifecycle lookups.

M5: `get_policy_binding_repository` and `get_protected_attribute_rule_repository`
are new — needed by the new Admin API surfaces and (the former) by the
generated ingestion routes' per-request policy resolution.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.engine import Engine

from gov_platform.audit.evidence_store import EvidenceStore
from gov_platform.db.repositories.plugin_registration import PluginRegistrationRepository
from gov_platform.db.repositories.policy_binding import PolicyBindingRepository
from gov_platform.db.repositories.protected_attribute_rule import ProtectedAttributeRuleRepository
from gov_platform.db.repositories.shadow_finding import ShadowFindingRepository
from gov_platform.db.repositories.system import SystemRepository
from gov_platform.normalization.service import NormalizationService


def get_normalization_service(request: Request) -> NormalizationService:
    service: NormalizationService = request.app.state.normalization_service
    return service


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


def get_db_engine(request: Request) -> Engine:
    """The one shared Engine, used directly by routes that need their own
    short-lived Session distinct from EvidenceStore's internal one — see
    api.app for why this is a single shared engine."""
    engine: Engine = request.app.state.db_engine
    return engine


def get_system_repository(request: Request) -> SystemRepository:
    repository: SystemRepository = request.app.state.system_repository
    return repository


def get_plugin_registration_repository(request: Request) -> PluginRegistrationRepository:
    repository: PluginRegistrationRepository = request.app.state.plugin_registration_repository
    return repository


def get_shadow_finding_repository(request: Request) -> ShadowFindingRepository:
    repository: ShadowFindingRepository = request.app.state.shadow_finding_repository
    return repository


def get_policy_binding_repository(request: Request) -> PolicyBindingRepository:
    repository: PolicyBindingRepository = request.app.state.policy_binding_repository
    return repository


def get_protected_attribute_rule_repository(
    request: Request,
) -> ProtectedAttributeRuleRepository:
    repository: ProtectedAttributeRuleRepository = (
        request.app.state.protected_attribute_rule_repository
    )
    return repository
