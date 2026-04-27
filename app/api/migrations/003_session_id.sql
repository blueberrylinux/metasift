-- Sandbox public-demo isolation: tag each conversation with the visitor's
-- session_id (set from the metasift_session_id cookie by the FastAPI session
-- middleware). When SANDBOX_MODE=1, /chat/conversations endpoints filter by
-- session_id so visitors never see each other's chats on a shared deployment.
--
-- Nullable so pre-existing conversations (from non-sandbox runs) keep their
-- existing visibility — when SANDBOX_MODE=0 the column is read but the
-- filter is bypassed, and the column stays NULL on new rows too. In sandbox,
-- pre-existing rows with NULL session_id are invisible to every visitor
-- (the filter is `session_id = ?`), which matches the "fresh nightly seed"
-- expectation per SANDBOX_PHASES.md §3.6.
ALTER TABLE conversations ADD COLUMN session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_session
    ON conversations(session_id, updated_at DESC);
