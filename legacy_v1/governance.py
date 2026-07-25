"""
MechGov 4-Layer Controller & Decision Engine
"""

import asyncio
from typing import Dict, Any
from schemas import GenericApplicationCase, GovernanceStatus, AuditRecord
from causal_engine import MutatisMutandisCausalEngine
from model_client import LocalModelClient
from monitor import DualIndicatorMonitor
from config import settings

class MechGovPipeline:
    def __init__(self):
        self.causal_engine = MutatisMutandisCausalEngine()
        self.client = LocalModelClient()
        self.monitor = DualIndicatorMonitor()

    async def process_and_audit(self, case_factual: GenericApplicationCase) -> Dict[str, Any]:
        trace = {
            "case_id": case_factual.case_id,
            "status": GovernanceStatus.APPROVED,
            "failed_layer": None,
            "candidate_factual": None,
            "candidate_cf": None,
            "protected_fields_detected": [],
            "mutations_made": {},
            "scores": {},
            "justified_offset": 0.0000,
            "residual_bias": 0.0000,
            "audit_note": "Passed all mechanical governance layers."
        }

        # LAYER 1: Input Bounds & Integrity
        if case_factual.user_metrics.get("dti", 0.0) > 0.8500:
            trace["status"] = GovernanceStatus.DENIED_RISK
            trace["failed_layer"] = "Layer 1 (Data Bounds Check)"
            trace["audit_note"] = "Extreme financial risk detected at input boundary."
            return trace

        # LAYER 2: Mechanical Pre-LLM Hard Gate
        if case_factual.user_metrics.get("credit_score", 800) < 400:
            trace["status"] = GovernanceStatus.DEFERRED_HARD_GATE
            trace["failed_layer"] = "Layer 2 (Pre-LLM Hard Gate)"
            trace["audit_note"] = "Credit score below mechanical threshold. Deferred to compliance officer."
            return trace

        # LAYER 3: Extract Latent U, Generate Twin, Concurrent Candidate Freezing
        case_factual.latent_u = self.causal_engine.extract_latent_solvency(case_factual)
        case_cf, protected_fields, mutations, justified_offset = self.causal_engine.generate_counterfactual_twin(case_factual)

        trace["protected_fields_detected"] = protected_fields
        trace["mutations_made"] = mutations
        trace["justified_offset"] = justified_offset

        # Concurrent Dual LLM Pass (Async Gathering)
        cand_factual, cand_cf = await asyncio.gather(
            self.client.generate_candidate_async(case_factual),
            self.client.generate_candidate_async(case_cf)
        )

        trace["candidate_factual"] = cand_factual
        trace["candidate_cf"] = cand_cf

        # LAYER 4: Dual-Indicator & Residual Bias Interceptor Gate
        scores = self.monitor.evaluate(case_factual, cand_factual)
        trace["scores"] = scores

        residual_bias = self.monitor.calculate_residual_bias(
            factual_metric=cand_factual.numerical_metric,
            cf_metric=cand_cf.numerical_metric,
            justified_offset=justified_offset
        )
        trace["residual_bias"] = residual_bias

        # Interception condition: Factual offer penalizes protected user relative to non-protected twin
        is_unfavorable = cand_factual.numerical_metric > cand_cf.numerical_metric

        if protected_fields and is_unfavorable and residual_bias >= settings.RESIDUAL_BIAS_THRESHOLD:
            trace["status"] = GovernanceStatus.BLOCKED_PREDATORY_BIAS
            trace["failed_layer"] = "Layer 4 (Mech Governance Interceptor)"
            trace["audit_note"] = (
                f"PREDATORY BIAS INTERCEPTED! Protected attributes detected: {protected_fields}. "
                f"User offered metric {cand_factual.numerical_metric:.4f} vs {cand_cf.numerical_metric:.4f} "
                f"for non-protected baseline {mutations}. "
                f"Residual Unjustified Bias Delta = {residual_bias:.4f} >= threshold ({settings.RESIDUAL_BIAS_THRESHOLD:.4f}). "
                f"Response hard-blocked from reaching user."
            )

        return trace