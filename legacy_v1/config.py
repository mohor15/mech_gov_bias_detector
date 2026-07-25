"""
System Configuration & Precision Settings
"""

import os
from pydantic_settings import BaseSettings

class SystemSettings(BaseSettings):
    APP_NAME: str = "Domain-Agnostic Mechanical Governance Framework"
    VERSION: str = "2.4.0-prod"
    
    # LLM Settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    LLM_TIMEOUT_SECONDS: float = 30.0000
    
    # Governance Thresholds (4 Decimal Accuracy)
    RESIDUAL_BIAS_THRESHOLD: float = 0.0050  # 0.5000% rate/score divergence tolerance
    PROFIT_SUITABILITY_GAP_THRESHOLD: float = 0.1500 # Max allowable margin exploitation gap
    
    # System Paths
    AUDIT_LOG_DIR: str = "audit_logs"
    
    # Precision
    DECIMAL_PRECISION: int = 4

    class Config:
        env_file = ".env"

settings = SystemSettings()