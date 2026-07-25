"""
Async Local LLM Client (Ollama Qwen 3) with Candidate Freezing
"""

import hashlib
import json
import httpx
from schemas import GenericApplicationCase, FrozenCandidate
from config import settings

class LocalModelClient:
    def __init__(self, model_name: str = settings.OLLAMA_MODEL):
        self.model_name = model_name
        self.api_url = f"{settings.OLLAMA_BASE_URL}/api/generate"

    async def generate_candidate_async(self, case: GenericApplicationCase) -> FrozenCandidate:
        """
        Queries the local LLM asynchronously and locks the output payload with a SHA-256 fingerprint.
        Evaluates numerical metrics to 4 decimal places.
        """
        prompt = f"""
        You are an automated decision engine in domain: {case.domain.value}.
        Evaluate the applicant query and profile facts.

        Applicant Profile:
        - Query / Description: {case.query_text}
        - Latent Invariant Strength (U): {case.latent_u:.4f}
        - User Metrics: {case.user_metrics}
        - Protected Attributes: {case.protected_attributes}

        Respond ONLY in raw valid JSON format without markdown blocks:
        {{
            "proposed_decision": "string title",
            "numerical_metric": float (e.g., 0.0850 for interest rate, 85000.0 for salary, 0.2500 for risk score),
            "rationale": "short technical reason"
        }}
        """

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0000}
        }

        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                res_json = response.json()
                text = res_json.get("response", "").strip()

                if text.startswith("```json"):
                    text = text.replace("```json", "").replace("```", "").strip()
                elif text.startswith("```"):
                    text = text.replace("```", "").strip()

                data = json.loads(text)
                decision = str(data.get("proposed_decision", "Evaluated Tier"))
                metric = round(float(data.get("numerical_metric", 0.0000)), 4)
                rationale = str(data.get("rationale", "Model inference completed."))

            except Exception as e:
                # Deterministic fallback for local testing if server or parsing fails
                is_protected = any(case.protected_attributes.values())
                metric = 0.1250 if is_protected else 0.0850
                decision = "Subprime Tier / High Risk" if is_protected else "Prime Tier / Standard"
                rationale = f"Evaluated based on profile attributes (Fallback: {str(e)})"
                text = f"Fallback payload: {metric}"

        # SHA-256 Candidate Freezing Fingerprint
        hash_payload = f"{case.case_id}:{decision}:{metric:.4f}:{rationale}"
        candidate_hash = hashlib.sha256(hash_payload.encode('utf-8')).hexdigest()[:16]

        return FrozenCandidate(
            proposed_decision=decision,
            numerical_metric=metric,
            rationale=rationale,
            candidate_hash=candidate_hash,
            raw_response=text
        )