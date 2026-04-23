"""Pydantic response models for the FastAPI layer.

Phase 0 shipped /health. Phase 1 adds composite score + coverage + refresh —
the dashboard's vertical slice. Subsequent phases fill in conversation,
review, viz, and report shapes as they're implemented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    """Sidebar status-dot payload."""

    ok: bool
    om: bool
    llm: bool
    duck: bool
    sqlite: bool
    version: str


# ── /analysis ─────────────────────────────────────────────────────────────────


class CompositeScore(BaseModel):
    """Dashboard headline metric. `scanned` is False until the deep scan has
    populated `cleaning_results` — the UI should render accuracy/quality as
    "—" in that state rather than "0%"."""

    coverage: float
    accuracy: float
    consistency: float
    quality: float
    composite: float
    scanned: bool = Field(
        description="True once the deep scan has run. When False, accuracy and "
        "quality are still in the payload as 0.0 so the composite math works, "
        "but the UI should show '—' for those two tiles."
    )


class CoverageRow(BaseModel):
    """One row of documentation coverage, keyed by (database, schema)."""

    database: str
    schema_: str = Field(alias="schema", serialization_alias="schema")
    total: int
    documented: int
    coverage_pct: float

    model_config = {"populate_by_name": True}


class CoverageResponse(BaseModel):
    rows: list[CoverageRow]


class RefreshResponse(BaseModel):
    """Payload returned after a synchronous `/analysis/refresh`. Counts mirror
    `duck.refresh_all()`; `run_id` ties back to the `scan_runs` row we logged
    so the sidebar's 'last scan N min ago' can pick it up."""

    run_id: int
    counts: dict[str, int]
    duration_ms: int


# ── /chat ─────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    """A single turn in the conversation history. Slice 1 accepts these as
    request input only; slice 2 adds retrieval from SQLite."""

    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    """Body for POST /chat/stream. Either pass `conversation_id` (history is
    loaded from SQLite and messages are persisted) or pass `history` directly
    for stateless / ad-hoc calls. If both are set, `conversation_id` wins."""

    question: str = Field(min_length=1)
    history: list[ChatMessage] | None = None
    conversation_id: str | None = None


class CreateConversationRequest(BaseModel):
    """Body for POST /chat/conversations. Title is optional — slice 3 adds a
    UI-driven auto-title on first exchange."""

    title: str | None = None


class ConversationSummary(BaseModel):
    """Row in GET /chat/conversations — no messages, keeps the list cheap."""

    id: str
    title: str | None = None
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    rows: list[ConversationSummary]


class PersistedMessage(BaseModel):
    """One row of a saved conversation's message history. `tool_trace` is the
    demuxed [{tool, args, result}] list from chat streaming, or None for user
    messages."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    tool_trace: list[dict] | None = None
    created_at: str


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummary
    messages: list[PersistedMessage]


# ── /llm ──────────────────────────────────────────────────────────────────


class LLMCatalogResponse(BaseModel):
    """Full OpenRouter catalog + the current selection. `source` is
    `"openrouter"` when the dynamic fetch succeeded, `"fallback"` when we're
    serving the offline curated list."""

    models: list[str]
    current: str
    source: Literal["openrouter", "fallback"]


class SetModelRequest(BaseModel):
    """Body for POST /llm/model. Only the shared model changes — api_key /
    base_url / per-task routing aren't exposed in this slice."""

    model: str = Field(min_length=1)

    @field_validator("model")
    @classmethod
    def _reject_whitespace(cls, v: str) -> str:
        # `min_length=1` counts characters, not stripped length. Without this
        # a whitespace-only string passes validation, then llm._clean() turns
        # it into None and the override silently reverts to the .env default.
        stripped = v.strip()
        if not stripped:
            raise ValueError("model must be a non-empty, non-whitespace string")
        return stripped


class ModelConfig(BaseModel):
    """Response shape after POST /llm/model. Just the active model id."""

    model: str


# ── /review ───────────────────────────────────────────────────────────────


class ReviewItem(BaseModel):
    """One pending suggestion. `key` is the stable identifier the UI sends
    back to accept/reject/edit endpoints — formatted `desc::<fqn>`,
    `doc::<fqn>`, or `pii::<fqn>::<col>` per the Streamlit impl."""

    kind: Literal["description", "pii_tag"]
    key: str
    fqn: str
    column: str | None = None
    old: str | None = None
    new: str
    confidence: float
    reason: str


class ReviewListResponse(BaseModel):
    rows: list[ReviewItem]


class AcceptEditedRequest(BaseModel):
    """Body for POST /review/{id}/accept-edited. `value` is the user-edited
    description text or PII tag id — validated against the tag allowlist
    for pii_tag items."""

    value: str = Field(min_length=1)


class ReviewAcceptResponse(BaseModel):
    """Echoes what was persisted to review_actions so the UI can update its
    local cache without a refetch round-trip."""

    action_id: int
    status: Literal["accepted", "rejected", "accepted_edited"]
    after_val: str
