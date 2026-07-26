"""Canonical ModelVersion — architecture §16.1, formalized in M1.

One version of a `System`'s model/decision logic. M1 auto-provisions a
single ``"unspecified"`` version per system during ingestion, since no
adapter wire format carries explicit version information yet — that's a
wire-format concern for a later milestone's adapters, not this schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

UNSPECIFIED_VERSION = "unspecified"


class ModelVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    system_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    created_at: datetime
