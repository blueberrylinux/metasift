-- MetaSift port — initial SQLite schema.
--
-- Holds the persistence surfaces Streamlit used st.session_state for:
--   * chat conversations + message history with tool traces
--   * review queue actions (accept/edit/reject audit trail)
--   * scan run timestamps (for "last scan N min ago" badges)
--   * LLM override session (single-user v1, see Port Risk Mitigation.md)
--
-- DuckDB stays in-memory for catalog analytics. SQLite is the session/audit
-- store. Never put om_* tables in here; never put conversations in DuckDB.

CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    tool_trace      TEXT,  -- JSON array of {tool, args, result}; NULL for user messages
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);

-- One row per accept/edit/reject action. Item IDs match the review queue
-- keys from _build_review_queue() — `desc::<fqn>`, `doc::<fqn>`, `pii::<fqn>::<col>`.
CREATE TABLE IF NOT EXISTS review_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,     -- 'description' | 'pii_tag'
    status      TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'accepted_edited')),
    reason      TEXT,
    before_val  TEXT,
    after_val   TEXT,
    fqn         TEXT NOT NULL,
    column_name TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_review_actions_item
    ON review_actions(item_id, id);

-- Scan run bookkeeping. Kinds: 'refresh', 'deep_scan', 'pii_scan',
-- 'dq_explain', 'dq_recommend', 'bulk_doc'.
CREATE TABLE IF NOT EXISTS scan_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    counts       TEXT,  -- JSON summary from the scan (e.g. {"analyzed": 9, "accuracy_pct": 67.5})
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_runs_kind_started
    ON scan_runs(kind, started_at DESC);

-- Migration bookkeeping. Each file in app/api/migrations/ gets one row after
-- it's applied; store.ensure_migrated() is idempotent on this.
CREATE TABLE IF NOT EXISTS _migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
