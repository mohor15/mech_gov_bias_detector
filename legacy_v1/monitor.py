"""
Dual-Indicator Monitor (S_user, P_org) & Residual Bias Calculator
Evaluated to 4 decimal places accuracy.
"""

from typing import Dict
from schemas import GenericApplicationCase, FrozenCandidate, DomainType

class DualIndicatorMonitor:
    def evaluate(self, case: GenericApplicationCase, candidate: FrozenCandidate) -> Dict[str, float]:
        metric = candidate.numerical_metric

        if case.domain == DomainType.FINANCE:
            rate = metric if metric <= 1.0 else metric / 100.0
            dti = case.user_metrics.get("dti", 0.3600)
            
            dti_safety = max(0.0000, 1.0000 - dti)
            rate_fairness = max(0.0000, 1.0000 - (rate / 0.2800))
            s_user = round((0.5000 * dti_safety) + (0.5000 * rate_fairness), 4)

            margin = max(0.0000, rate - 0.0400)
            p_org = round(min(1.0000, margin / 0.1500), 4)

        elif case.domain == DomainType.HIRING:
            salary = metric
            salary_normalized = min(1.0000, salary / 150000.0)
            s_user = round(salary_normalized, 4)
            p_org = round(1.0000 - (salary_normalized * 0.5000), 4)

        else:
            s_user = round(0.7500, 4)
            p_org = round(0.7500, 4)

        return {
            "user_suitability_score": s_user,
            "organization_benefit_score": p_org,
            "margin_gap": round(p_org - s_user, 4)
        }

    def calculate_residual_bias(
        self, 
        factual_metric: float, 
        cf_metric: float, 
        justified_offset: float = 0.0000
    ) -> float:
        """
        Calculates residual unjustified bias:
        Delta_residual = Max(0.0000, |Factual_Metric - CF_Metric| - Justified_Offset)
        """
        raw_spread = abs(factual_metric - cf_metric)
        residual = max(0.0000, raw_spread - justified_offset)
        return round(residual, 4)