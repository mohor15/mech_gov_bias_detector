"""SQLAlchemy declarative models — a query-time mapping onto the schema
`infra/migrations/*.sql` owns. These models are never used to generate DDL
(no `Base.metadata.create_all()` anywhere in this codebase as of M1) — that
would make two sources of schema truth. If a model and a migration ever
disagree, the migration is correct and the model is the bug.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SystemRow(Base):
    __tablename__ = "systems"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelVersionRow(Base):
    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    system_id: Mapped[str] = mapped_column(String, ForeignKey("systems.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionEventRow(Base):
    __tablename__ = "decision_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    model_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("model_versions.id"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    subject_ref: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_features: Mapped[str] = mapped_column(Text, nullable=False)
    protected_attribute_refs: Mapped[str] = mapped_column(Text, nullable=False)
    decision_output: Mapped[str] = mapped_column(Text, nullable=False)


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_event_id: Mapped[str] = mapped_column(
        String, ForeignKey("decision_events.id"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    metric_values: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VerdictRow(Base):
    __tablename__ = "verdicts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_event_id: Mapped[str] = mapped_column(
        String, ForeignKey("decision_events.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VerdictFindingRow(Base):
    __tablename__ = "verdict_findings"

    verdict_id: Mapped[str] = mapped_column(String, ForeignKey("verdicts.id"), primary_key=True)
    finding_id: Mapped[str] = mapped_column(String, ForeignKey("findings.id"), primary_key=True)


class ProtectedAttributeResolutionRow(Base):
    __tablename__ = "protected_attribute_resolutions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_event_id: Mapped[str] = mapped_column(
        String, ForeignKey("decision_events.id"), nullable=False
    )
    attribute_name: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    proxy_basis: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PluginRegistrationRow(Base):
    __tablename__ = "plugin_registrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plugin_type: Mapped[str] = mapped_column(String, nullable=False)
    plugin_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShadowFindingRow(Base):
    __tablename__ = "shadow_findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_event_id: Mapped[str] = mapped_column(
        String, ForeignKey("decision_events.id"), nullable=False
    )
    plugin_registration_id: Mapped[str] = mapped_column(
        String, ForeignKey("plugin_registrations.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    metric_values: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceChainRow(Base):
    __tablename__ = "evidence_chain"

    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_event_id: Mapped[str] = mapped_column(String, nullable=False)
    verdict_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # M5: nullable -- signing applies going forward only, see
    # schemas/verdict.py's docstring on why M0-M4 rows are never rewritten.
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String, nullable=True)


class PolicyBindingRow(Base):
    __tablename__ = "policy_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProtectedAttributeRuleRow(Base):
    __tablename__ = "protected_attribute_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    attribute_name: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    proxy_of: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PopulationPolicyBindingRow(Base):
    __tablename__ = "population_policy_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    system_id: Mapped[str] = mapped_column(String, ForeignKey("systems.id"), nullable=False)
    population_policy_id: Mapped[str] = mapped_column(String, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PopulationFindingRow(Base):
    __tablename__ = "population_findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    population_policy_id: Mapped[str] = mapped_column(String, nullable=False)
    population_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    system_id: Mapped[str] = mapped_column(String, ForeignKey("systems.id"), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    metric_values: Mapped[str] = mapped_column(Text, nullable=False)
    classification_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Never None in practice (unlike evidence_chain's M0-M4 backfill case --
    # population_findings did not exist before signing did), but nullable
    # at the schema level for the same reason evidence_chain's are: a
    # signature can only ever be set once, at INSERT time (see migration
    # 0015's REVOKE UPDATE, DELETE).
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
