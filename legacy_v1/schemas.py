"""
Domain-Agnostic Data Models & Precision Converters
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class DomainType(str, Enum):
    FINANCE = "FINANCE"
    HIRING = "HIRING"
    LEGAL = "LEGAL"
    HEALTHCARE = "HEALTHCARE"
    INSURANCE = "INSURANCE"

class GovernanceStatus(str, Enum):
    APPROVED = "APPROVED"
    DENIED_RISK = "DENIED_RISK"
    DEFERRED_HARD_GATE = "DEFERRED_HARD_GATE"
    BLOCKED_PREDATORY_BIAS = "BLOCKED_PREDATORY_BIAS"

class ProtectedAttribute(BaseModel):
    attribute_type: str = Field(..., description="e.g., country, zip_code, gender, race, age_group")
    factual_value: str = Field(..., description="User's entry value")
    is_protected: bool = False
    justified_offset: float = Field(default=0.0000, description="Legitimate risk offset (4 decimals)")

class GenericApplicationCase(BaseModel):
    case_id: str
    domain: DomainType
    query_text: str
    user_metrics: Dict[str, float] = Field(default_factory=dict, description="Normalized metrics (0.0000 to 1.0000)")
    protected_attributes: Dict[str, str] = Field(default_factory=dict, description="e.g. {'country': 'India', 'gender': 'Female'}")
    latent_u: float = Field(default=0.0000, description="Latent Solvency / Qualification Factor U (0.0000 to 1.0000)")

    def round_metrics(self):
        """Ensures all user metric values are evaluated to 4 decimal places accuracy."""
        for k, v in self.user_metrics.items():
            self.user_metrics[k] = round(float(v), 4)

class FrozenCandidate(BaseModel):
    proposed_decision: str = Field(..., description="e.g., Credit Approval, Job Recommendation, Bail Amount")
    numerical_metric: float = Field(..., description="Key decision number (Interest Rate, Salary Offer, Risk Score)")
    rationale: str
    candidate_hash: str = Field(..., description="SHA-256 cryptographic fingerprint")
    raw_response: str

class AuditRecord(BaseModel):
    transaction_id: str
    timestamp_utc: str
    domain: DomainType
    case_id: str
    status: GovernanceStatus
    failed_layer: Optional[str] = None
    latent_u: float
    factual_offer_metric: float
    baseline_offer_metric: float
    justified_offset: float
    residual_bias: float
    user_suitability_score: float
    organization_benefit_score: float
    mutations_map: Dict[str, str]
    audit_note: str