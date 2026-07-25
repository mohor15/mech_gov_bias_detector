"""
Structural Causal Model Engine (Pearl's 3 Steps)
Extracts Latent Solvency/Qualification Factor U and Mutates Protected Attributes.
"""

from copy import deepcopy
from typing import Tuple, List, Dict
from schemas import GenericApplicationCase, DomainType
from registry import ProtectedAttributeRegistry

class MutatisMutandisCausalEngine:
    def __init__(self):
        self.registry = ProtectedAttributeRegistry()

    def extract_latent_solvency(self, case: GenericApplicationCase) -> float:
        """
        Calculates hidden invariant latent solvency / qualification strength U in range [0.0000, 1.0000].
        Evaluated to 4 decimal places accuracy.
        """
        metrics = case.user_metrics
        
        if case.domain == DomainType.FINANCE:
            income = metrics.get("annual_income", 60000.0)
            debt = metrics.get("monthly_debt", 1800.0)
            credit_score = metrics.get("credit_score", 700.0)
            
            monthly_income = income / 12.0000
            dti = debt / monthly_income if monthly_income > 0 else 1.0000
            risk_score = 1.0000 - ((max(300.0, min(850.0, credit_score)) - 300.0) / 550.0)
            income_cap = min(1.0000, income / 100000.0000)
            
            composite_risk = (0.4000 * risk_score) + (0.4000 * dti) + (0.2000 * (1.0000 - income_cap))
            latent_u = max(0.0000, min(1.0000, 1.0000 - composite_risk))
            
        elif case.domain == DomainType.HIRING:
            exp_years = metrics.get("experience_years", 5.0)
            skill_score = metrics.get("technical_skill_score", 0.8000)
            edu_score = metrics.get("education_score", 0.7500)
            
            exp_capacity = min(1.0000, exp_years / 10.0000)
            latent_u = (0.4000 * skill_score) + (0.4000 * exp_capacity) + (0.2000 * edu_score)
            
        else:
            # Default generic metric aggregator
            scores = list(metrics.values()) if metrics else [0.5000]
            latent_u = sum(scores) / len(scores)

        return round(latent_u, 4)

    def generate_counterfactual_twin(
        self, 
        original_case: GenericApplicationCase
    ) -> Tuple[GenericApplicationCase, List[str], Dict[str, str], float]:
        """
        Scans all protected attributes, mutates protected ones to non-protected baseline values,
        while holding latent U and core qualifications 100% constant.
        """
        latent_u = self.extract_latent_solvency(original_case)
        twin = deepcopy(original_case)
        twin.case_id = f"CF-{original_case.case_id}"
        twin.latent_u = latent_u

        protected_fields_detected = []
        mutations_made = {}
        total_justified_offset = 0.0000

        for attr_key, attr_val in original_case.protected_attributes.items():
            if self.registry.is_value_protected(attr_key, attr_val):
                protected_fields_detected.append(attr_key)
                baseline_val = self.registry.sample_random_non_protected_baseline(attr_key)
                twin.protected_attributes[attr_key] = baseline_val
                mutations_made[attr_key] = f"{attr_val} -> {baseline_val}"
                total_justified_offset += self.registry.get_justified_offset(attr_key, attr_val)

        return twin, protected_fields_detected, mutations_made, round(total_justified_offset, 4)