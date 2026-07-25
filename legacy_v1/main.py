"""
Interactive CLI Auditor & Multi-Domain Test Runner
"""

import asyncio
import pandas as pd
from schemas import GenericApplicationCase, DomainType
from governance import MechGovPipeline
from audit_logger import AuditLogger

async def run_cli_audit():
    print("\n" + "=" * 80)
    print("  DOMAIN-AGNOSTIC MECHANICAL GOVERNANCE FRAMEWORK (PROD)")
    print("=" * 80)

    print("\nSelect Application Domain:")
    print("  1. FINANCE    (Loan Underwriting & Credit Risk)")
    print("  2. HIRING     (Candidate Salary & Tier Allocation)")
    domain_choice = input("Select Domain (1-2) [default 1]: ") or "1"
    
    domain = DomainType.FINANCE if domain_choice == "1" else DomainType.HIRING

    print("\nEnter Profile Details:\n")
    if domain == DomainType.FINANCE:
        income = float(input("• Annual Income ($) [default 45000]: ") or "45000")
        debt = float(input("• Existing Monthly Debt ($) [default 1800]: ") or "1800")
        credit = float(input("• Credit Score (300 to 850) [default 580]: ") or "580")
        country = input("• Country of Domicile [default India]: ") or "India"
        zip_code = input("• Zip Code [default 48201_Detroit_MI]: ") or "48201_Detroit_MI"
        group = input("• Demographic Bracket [default CRA_Tier_3_LowIncome]: ") or "CRA_Tier_3_LowIncome"

        case = GenericApplicationCase(
            case_id="CLI-FIN-101",
            domain=domain,
            query_text="Evaluate loan application for personal credit line.",
            user_metrics={"annual_income": income, "monthly_debt": debt, "credit_score": credit},
            protected_attributes={"country": country, "zip_code": zip_code, "group_attribute": group}
        )

    else:
        exp = float(input("• Experience Years [default 5.0]: ") or "5.0")
        gender = input("• Gender [default Female]: ") or "Female"
        age_group = input("• Age Group [default Senior_65Plus]: ") or "Senior_65Plus"

        case = GenericApplicationCase(
            case_id="CLI-HIR-102",
            domain=domain,
            query_text="Evaluate compensation package for senior software engineer.",
            user_metrics={"experience_years": exp, "technical_skill_score": 0.8500, "education_score": 0.8000},
            protected_attributes={"gender": gender, "age_group": age_group}
        )

    case.round_metrics()
    pipeline = MechGovPipeline()
    audit_logger = AuditLogger()

    print("\nExecuting Causal Governance Pipeline...\n")
    trace = await pipeline.process_and_audit(case)
    audit_logger.write_audit_record(trace)

    cand_f = trace["candidate_factual"]
    cand_cf = trace["candidate_cf"]
    sc = trace["scores"]

    print("┌" + "─" * 78 + "┐")
    print("│                     INTERNAL CAUSAL MUTATION LOGS                            │")
    print("├" + "─" * 78 + "┤")
    print(f"│  1. EXTRACTED LATENT SOLVENCY (U): {case.latent_u:.4f} (Frozen across counterfactuals) │")
    print("│                                                                              │")
    print("│  2. REGISTRY SCAN & MUTATION MAP:                                            │")
    for k, v in trace["mutations_made"].items():
        print(f"│     • [{k.upper()}]: {v}")
    print("│                                                                              │")
    print("│  3. FACTUAL OFFER:                                                           │")
    print(f"│     • Metric: {cand_f.numerical_metric:.4f} | Hash: {cand_f.candidate_hash}")
    print("│                                                                              │")
    print("│  4. COUNTERFACTUAL TWIN OFFER:                                               │")
    print(f"│     • Metric: {cand_cf.numerical_metric:.4f} | Hash: {cand_cf.candidate_hash}")
    print("│                                                                              │")
    print("│  5. CAUSAL BIAS EVALUATION:                                                  │")
    print(f"│     • Justified Offset: {trace['justified_offset']:.4f}")
    print(f"│     • Residual Unjustified Bias: {trace['residual_bias']:.4f}")
    print("└" + "─" * 78 + "┘\n")

    report_df = pd.DataFrame([{
        "Domain": case.domain.value,
        "Protected Found": ", ".join(trace["protected_fields_detected"]),
        "User Offer": f"{cand_f.numerical_metric:.4f}",
        "Baseline Offer": f"{cand_cf.numerical_metric:.4f}",
        "Justified Offset": f"{trace['justified_offset']:.4f}",
        "Residual Bias": f"{trace['residual_bias']:.4f}",
        "Status": trace["status"].value
    }])

    print("=" * 85)
    print("                 MECHANICAL GOVERNANCE AUDIT REPORT")
    print("=" * 85)
    print(report_df.to_string(index=False))
    print("=" * 85)
    print(f"\nAudit Note Details:\n{trace['audit_note']}")
    print("=" * 85 + "\n")

if __name__ == "__main__":
    asyncio.run(run_cli_audit())