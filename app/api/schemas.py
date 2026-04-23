"""Pydantic response models for the FastAPI layer.

Phase 0 keeps these minimal — just enough to type the /health endpoint and
establish the pattern. Subsequent phases fill in conversation, review, viz,
and report shapes as they're implemented.
"""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Sidebar status-dot payload."""

    ok: bool
    om: bool
    llm: bool
    duck: bool
    sqlite: bool
    version: str
