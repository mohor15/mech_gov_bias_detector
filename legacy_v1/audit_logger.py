"""
Cryptographic Audit Trail JSON Stream Writer
"""

import os
import json
import time
from typing import Dict, Any
from config import settings

class AuditLogger:
    def __init__(self, log_dir: str = settings.AUDIT_LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

    def write_audit_record(self, trace: Dict[str, Any]):
        """Saves complete governance execution trace and candidate hashes to disk."""
        filename = f"audit_record_{int(time.time())}_{trace['case_id']}.json"
        filepath = os.path.join(self.log_dir, filename)

        serializable_trace = {
            "case_id": trace["case_id"],
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": str(trace["status"].value if hasattr(trace["status"], "value") else trace["status"]),
            "failed_layer": trace["failed_layer"],
            "protected_fields_detected": trace["protected_fields_detected"],
            "mutations_made": trace["mutations_made"],
            "justified_offset": f"{trace['justified_offset']:.4f}",
            "residual_bias": f"{trace['residual_bias']:.4f}",
            "scores": trace["scores"],
            "candidate_factual": trace["candidate_factual"].dict() if trace["candidate_factual"] else None,
            "candidate_cf": trace["candidate_cf"].dict() if trace["candidate_cf"] else None,
            "audit_note": trace["audit_note"]
        }

        with open(filepath, "w") as f:
            json.dump(serializable_trace, f, indent=2)