"""Pydantic response models for the FastAPI layer.

Phase 0 shipped /health. Phase 1 adds composite score + coverage + refresh —
the dashboard's vertical slice. Subsequent phases fill in conversation,
review, viz, and report shapes as they're implemented.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    """Sidebar status-dot payload."""

    ok: bool
    om: bool
    llm: bool
    duck: bool
    sqlite: bool
    version: str
    # True when the FastAPI process was started with SANDBOX_MODE=1 — the
    # React app reads this on boot to render the read-only banner, hide
    # accept/reject buttons, and surface the BYO-key modal on first chat.
    sandbox: bool = False


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


class DataSourceRow(BaseModel):
    """One service connected to OpenMetadata, with its ingested-table count.

    `type` is the connector flavour (`Mysql`, `Postgres`, `Tableau`, …) the
    service was registered with. `tables` is derived from `om_tables` —
    services whose kind isn't `database` will always show 0 since only
    database connectors produce tables.
    """

    service: str
    kind: str
    type: str | None = None
    tables: int


class DataSourcesResponse(BaseModel):
    rows: list[DataSourceRow]


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

    @field_validator("question")
    @classmethod
    def _reject_whitespace(cls, v: str) -> str:
        # min_length=1 counts characters, not stripped length, so "   " passes
        # without this — and the agent then wastes an LLM call on nothing.
        stripped = v.strip()
        if not stripped:
            raise ValueError("question must be a non-empty, non-whitespace string")
        return stripped


class CreateConversationRequest(BaseModel):
    """Body for POST /chat/conversations. Title is optional — slice 3 adds a
    UI-driven auto-title on first exchange."""

    title: str | None = None


class RenameConversationRequest(BaseModel):
    """Body for PATCH /chat/conversations/{id}. Empty string clears the
    title (useful if the user deletes the inline-edit text)."""

    title: str = Field(max_length=200)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


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


class TaskModelMap(BaseModel):
    """Per-task model routing. Empty string means "no override — use the
    .env-configured default" for that task."""

    toolcall: str = ""
    reasoning: str = ""
    description: str = ""
    stale: str = ""
    scoring: str = ""
    classification: str = ""


class LLMConfigResponse(BaseModel):
    """Snapshot for the LLM setup screen. Never includes the raw API key —
    `api_key_preview` is the masked last-4 so the UI can confirm a key
    is active without letting it be copy-paste-leaked."""

    api_key_set: bool
    api_key_preview: str
    base_url: str
    model: str
    per_task_models: TaskModelMap
    env_defaults: TaskModelMap


class SetLLMConfigRequest(BaseModel):
    """Body for POST /llm/config. All fields optional — omit to keep
    the current value. Per-task overrides inside `per_task_models` use
    empty string as the "clear" signal (distinct from omitted)."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    per_task_models: TaskModelMap | None = None


class LLMTestRequest(BaseModel):
    """Optional body for POST /llm/test. If any field is set, the test
    uses those values instead of the persisted override — lets the UI
    verify a candidate config before saving it."""

    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class LLMTestResponse(BaseModel):
    """One ping-and-decode round trip. `response` is the first 200 chars
    of what the model returned to the canonical test prompt; `error` is
    set when `ok` is False."""

    ok: bool
    model: str
    base_url: str
    latency_ms: int
    response: str
    error: str | None = None


class ValidateKeyRequest(BaseModel):
    """Body for POST /llm/validate-key. Used by the sandbox BYO-key modal
    to confirm a user's pasted OpenRouter key before persisting it to
    localStorage. Cheap — one HTTP call to OpenRouter's /auth/key, no
    LLM completion."""

    key: str = Field(min_length=1)

    @field_validator("key")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("key must be a non-empty, non-whitespace string")
        return stripped


class ValidateKeyResponse(BaseModel):
    """Result of POST /llm/validate-key. `ok` False with an `error` string
    surfaces the OpenRouter rejection reason (rate-limited, invalid key,
    expired, etc.) so the React app can render an actionable message."""

    ok: bool
    error: str | None = None


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


# ── /scans ────────────────────────────────────────────────────────────────


class BulkDocRequest(BaseModel):
    """Body for POST /scans/bulk-doc. The Streamlit agent path defaults to
    20 tables per run to bound LLM cost; matching that here."""

    schema_name: str = Field(min_length=1)
    max_tables: int = Field(default=20, ge=1, le=500)

    @field_validator("schema_name")
    @classmethod
    def _reject_whitespace(cls, v: str) -> str:
        # Same bug class as SetModelRequest — `min_length=1` lets `"   "` through,
        # and the engine then silently no-ops rather than 422'ing.
        stripped = v.strip()
        if not stripped:
            raise ValueError("schema_name must be a non-empty, non-whitespace string")
        return stripped


class ScanRun(BaseModel):
    """One row from the scan_runs audit table. `counts` is whatever the
    engine's run_fn returned; `error` is set when status == 'failed'."""

    id: int
    kind: str
    started_at: str
    finished_at: str | None = None
    status: Literal["running", "completed", "failed", "cancelled"]
    counts: dict[str, Any] | None = None
    error: str | None = None


class ScanStatusResponse(BaseModel):
    """Last-run info per kind. None when a kind has never run. Keys are the
    stable scan-kind identifiers the SSE endpoints start scans under."""

    kinds: dict[str, ScanRun | None]


class ActiveScanResponse(BaseModel):
    """The single in-flight scan, or None. The sandbox React app polls this
    on a 5s cadence to disable scan buttons while another visitor's scan is
    mid-flight (single-worker API serializes scans of the same kind, but
    cross-kind concurrency is also UX-disruptive on a shared deployment)."""

    active: ScanRun | None


# ── /viz ──────────────────────────────────────────────────────────────────


class VizTabMeta(BaseModel):
    """One tab's metadata — slug is the URL-safe identifier; label carries
    the emoji-prefixed display string from Streamlit's `st.tabs` row;
    caption is the one-liner under it."""

    slug: str
    label: str
    caption: str


class VizListResponse(BaseModel):
    tabs: list[VizTabMeta]


class VizFigureResponse(BaseModel):
    """`figure` is the Plotly JSON dict from `fig.to_dict()` (data + layout
    + frames). `None` when the builder had no data — the UI renders an
    empty-state hint pointing at the sidebar scan that would populate it."""

    figure: dict[str, Any] | None


# ── /dq ───────────────────────────────────────────────────────────────────


FixType = Literal["schema_change", "etl_investigation", "data_correction", "upstream_fix", "other"]
Severity = Literal["critical", "recommended", "nice-to-have"]


class DQSummaryResponse(BaseModel):
    """Headline counts from om_test_cases. `failing_tables` is distinct
    table_fqn under status='Failed'."""

    total: int
    failed: int
    passed: int
    failing_tables: int


class DQExplanation(BaseModel):
    """LLM-written plain-English breakdown of a failing test. `fix_type` is
    the classifier bucket the UI maps to a chip — value must be one of the
    five allowlist entries (`other` is the fallback)."""

    summary: str
    likely_cause: str
    next_step: str
    fix_type: FixType


class DQFailure(BaseModel):
    """One failing DQ test. `explanation` is null when the explain-scan
    hasn't produced a row for this test yet."""

    test_id: str
    test_name: str
    table_fqn: str
    column_name: str | None = None
    test_definition_name: str | None = None
    result_message: str | None = None
    explanation: DQExplanation | None = None


class DQFailuresResponse(BaseModel):
    """Failing tests + the summary strip the UI renders above the list.
    `explanations_loaded` tells the UI whether to nudge the user to click
    the 🧪 Explain DQ scan in the sidebar."""

    summary: DQSummaryResponse
    rows: list[DQFailure]
    explanations_loaded: bool


class DQRecommendation(BaseModel):
    """One suggested DQ test. `parameters` is the list of
    {name, value}-shaped dicts OpenMetadata expects; passed through as-is
    so the UI can render them in a copy-to-clipboard card."""

    table_fqn: str
    column_name: str | None = None
    test_definition: str
    parameters: list[dict[str, Any]]
    rationale: str
    severity: Severity


class DQRecommendationsResponse(BaseModel):
    """Recommendations list + a flag telling the UI whether the
    dq_recommend scan has run. Empty `rows` is ambiguous without it
    (could mean "no gaps" OR "scan not run")."""

    rows: list[DQRecommendation]
    scan_run: bool


class DQRiskRow(BaseModel):
    """One row in the catalog-wide DQ risk ranking. `risk_score` is
    failed_tests * (direct + 0.5*transitive + 2*pii_downstream) —
    zero when either side is zero."""

    fqn: str
    failed_tests: int
    direct: int
    transitive: int
    pii_downstream: int
    risk_score: float


class DQRiskResponse(BaseModel):
    rows: list[DQRiskRow]


class DQImpactResponse(BaseModel):
    """Per-table drilldown. Shape matches `analysis.dq_impact()` directly —
    safe to expose as-is since it's already meant for UI consumption."""

    fqn: str
    failed_tests: int
    failing_test_names: list[str]
    direct: int
    transitive: int
    pii_downstream: int
    downstream_fqns: list[str]
    risk_score: float


# ── /report ───────────────────────────────────────────────────────────────


class ReportResponse(BaseModel):
    """Executive report — a single markdown string plus the ISO-8601 UTC
    timestamp of generation. The UI renders `markdown` with react-markdown +
    remark-gfm and offers it as a .md download."""

    markdown: str
    generated_at: str


# ── /om (OpenMetadata connection) ─────────────────────────────────────────


class OMConfigResponse(BaseModel):
    """Current OM connection settings + provenance.

    `host` is the OM root (no `/api`). `has_token` is true if either an
    override is set or `.env` has a token. `source` tells the UI where the
    active token comes from so it can show "from .env" vs "set via UI"."""

    host: str
    has_token: bool
    source: Literal["env", "sqlite", "unset"]


class OMConfigRequest(BaseModel):
    """Save a new OM connection. The server validates by hitting OM's
    `/v1/system/version` with the new credentials before persisting — a
    failed validation surfaces the OM error verbatim and nothing is saved."""

    host: str = Field(..., min_length=1)
    jwt: str = Field(..., min_length=1)
