"""
FastAPI Microservice Endpoint
"""

from fastapi import FastAPI, HTTPException
from schemas import GenericApplicationCase, DomainType
from governance import MechGovPipeline
from audit_logger import AuditLogger

app = FastAPI(
    title="Domain-Agnostic Mechanical Governance Microservice",
    version="2.4.0-prod"
)

pipeline = MechGovPipeline()
audit_logger = AuditLogger()

@app.get("/healthz")
async def health_check():
    return {"status": "HEALTHY"}

@app.post("/v1/governance/audit")
async def audit_application(case: GenericApplicationCase):
    case.round_metrics()
    trace = await pipeline.process_and_audit(case)
    audit_logger.write_audit_record(trace)

    return {
        "case_id": trace["case_id"],
        "status": trace["status"],
        "failed_layer": trace["failed_layer"],
        "latent_u": f"{case.latent_u:.4f}",
        "user_metric": f"{trace['candidate_factual'].numerical_metric:.4f}" if trace['candidate_factual'] else "0.0000",
        "baseline_metric": f"{trace['candidate_cf'].numerical_metric:.4f}" if trace['candidate_cf'] else "0.0000",
        "justified_offset": f"{trace['justified_offset']:.4f}",
        "residual_bias": f"{trace['residual_bias']:.4f}",
        "audit_note": trace["audit_note"]
    }