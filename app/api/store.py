"""SQLite persistence layer.

Module-level functions matching the existing `app.clients.duck` / `app.clients.llm`
pattern — no class facade. Each function takes the connection as first arg or
pulls from the shared singleton via `get_conn()`.

Surfaces held in SQLite:
    * conversations + messages with tool traces
    * review_actions audit trail
    * scan_runs bookkeeping ("last scan N min ago")
    * _migrations tracking

DuckDB (in-memory) stays the catalog analytics cache — never mix the two.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.api.config import api_settings

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_conn: sqlite3.Connection | None = None
_conn_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    """Return the shared SQLite connection. Ensures migrations have run once."""
    global _conn
    with _conn_lock:
        if _conn is None:
            path = api_settings.sqlite_path
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(
                str(path),
                check_same_thread=False,  # single-worker FastAPI — threads ok
                isolation_level=None,  # autocommit; we manage explicit transactions
            )
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON;")
            _conn.execute("PRAGMA journal_mode = WAL;")
            _ensure_migrated(_conn)
        return _conn


def _ensure_migrated(conn: sqlite3.Connection) -> None:
    """Apply every .sql file in migrations/ that hasn't been applied yet.

    Idempotent. Migration files are ordered lexicographically (001_, 002_, …).
    """
    # Bootstrap the _migrations table — the first migration creates it, but
    # applying it depends on checking it. Chicken-and-egg solved by trying.
    try:
        conn.execute("SELECT 1 FROM _migrations LIMIT 1")
        applied = {row[0] for row in conn.execute("SELECT filename FROM _migrations").fetchall()}
    except sqlite3.OperationalError:
        applied = set()

    for mig_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if mig_path.name in applied:
            continue
        logger.info(f"Applying migration {mig_path.name}")
        sql = mig_path.read_text()
        with conn:  # transaction
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO _migrations (filename) VALUES (?)",
                (mig_path.name,),
            )


def ping() -> bool:
    """Liveness probe used by the /health endpoint."""
    try:
        get_conn().execute("SELECT 1").fetchone()
        return True
    except Exception as e:
        logger.warning(f"SQLite ping failed: {e}")
        return False


# ── Conversations ─────────────────────────────────────────────────────────────


def new_conversation(title: str | None = None) -> str:
    """Create a new conversation, return its ID."""
    convo_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?)",
            (convo_id, title),
        )
    return convo_id


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    """Most recent conversations first."""
    rows = (
        get_conn()
        .execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def get_conversation(convo_id: str) -> dict[str, Any] | None:
    """Return {conversation, messages} or None if not found."""
    conn = get_conn()
    convo = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (convo_id,),
    ).fetchone()
    if convo is None:
        return None
    msgs = conn.execute(
        "SELECT id, role, content, tool_trace, created_at FROM messages "
        "WHERE conversation_id = ? ORDER BY id",
        (convo_id,),
    ).fetchall()
    return {
        "conversation": dict(convo),
        "messages": [
            {
                **dict(m),
                "tool_trace": json.loads(m["tool_trace"]) if m["tool_trace"] else None,
            }
            for m in msgs
        ],
    }


def append_message(
    convo_id: str,
    role: str,
    content: str,
    tool_trace: list[dict] | None = None,
) -> int:
    """Append a message; bump the conversation's updated_at."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_trace) VALUES (?, ?, ?, ?)",
            (convo_id, role, content, json.dumps(tool_trace) if tool_trace else None),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), convo_id),
        )
        return cur.lastrowid or 0


def append_exchange(
    convo_id: str,
    user_content: str,
    assistant_content: str,
    tool_trace: list[dict] | None = None,
) -> tuple[int, int]:
    """Atomically persist one user→assistant turn. Either both rows land or
    neither — prevents dangling user messages if the assistant write fails.

    The connection is opened in autocommit mode (`isolation_level=None`,
    see `get_conn`), so `with conn` wouldn't give us rollback here. Explicit
    `BEGIN` / `COMMIT` / `ROLLBACK` is the only safe way.
    """
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        user_cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_trace) VALUES (?, ?, ?, ?)",
            (convo_id, "user", user_content, None),
        )
        asst_cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_trace) VALUES (?, ?, ?, ?)",
            (
                convo_id,
                "assistant",
                assistant_content,
                json.dumps(tool_trace) if tool_trace else None,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), convo_id),
        )
        conn.execute("COMMIT")
        return user_cur.lastrowid or 0, asst_cur.lastrowid or 0
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ── Review actions ────────────────────────────────────────────────────────────


def record_review_action(
    item_id: str,
    kind: str,
    status: str,
    *,
    fqn: str,
    column_name: str | None = None,
    before_val: str | None = None,
    after_val: str | None = None,
    reason: str | None = None,
) -> int:
    """Append a row to review_actions. Returns the new row's ID."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO review_actions "
            "(item_id, kind, status, reason, before_val, after_val, fqn, column_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, kind, status, reason, before_val, after_val, fqn, column_name),
        )
        return cur.lastrowid or 0


def review_history(item_id: str) -> list[dict[str, Any]]:
    rows = (
        get_conn()
        .execute(
            "SELECT * FROM review_actions WHERE item_id = ? ORDER BY id",
            (item_id,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def review_stats(days: int = 7) -> dict[str, int]:
    """Quick counts for the sidebar / header badges."""
    rows = (
        get_conn()
        .execute(
            "SELECT status, COUNT(*) AS n FROM review_actions "
            "WHERE created_at >= datetime('now', ?) GROUP BY status",
            (f"-{int(days)} days",),
        )
        .fetchall()
    )
    out = {"accepted": 0, "rejected": 0, "accepted_edited": 0}
    for r in rows:
        out[r["status"]] = r["n"]
    return out


# ── Scan runs ─────────────────────────────────────────────────────────────────


def start_scan(kind: str) -> int:
    """Record a scan starting; return its run_id for the finish call."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (kind, status) VALUES (?, 'running')",
            (kind,),
        )
        return cur.lastrowid or 0


def finish_scan(
    run_id: int,
    *,
    status: str = "completed",
    counts: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scan_runs SET finished_at = ?, status = ?, counts = ?, error = ? WHERE id = ?",
            (
                datetime.now(UTC).isoformat(),
                status,
                json.dumps(counts) if counts else None,
                error,
                run_id,
            ),
        )


def last_scan(kind: str) -> dict[str, Any] | None:
    """Most recent scan of a given kind, or None."""
    row = (
        get_conn()
        .execute(
            "SELECT * FROM scan_runs WHERE kind = ? ORDER BY started_at DESC LIMIT 1",
            (kind,),
        )
        .fetchone()
    )
    if row is None:
        return None
    d = dict(row)
    if d.get("counts"):
        try:
            d["counts"] = json.loads(d["counts"])
        except json.JSONDecodeError:
            pass
    return d


def last_scans(kinds: Iterable[str] | None = None) -> dict[str, dict[str, Any] | None]:
    """Map each kind → its latest run, or None. Handy for sidebar badges."""
    default_kinds = (
        "refresh",
        "deep_scan",
        "pii_scan",
        "dq_explain",
        "dq_recommend",
        "bulk_doc",
    )
    kinds_list = list(kinds) if kinds is not None else list(default_kinds)
    return {k: last_scan(k) for k in kinds_list}


def scan_is_running(kind: str) -> bool:
    """True if there's an in-flight run of this kind. Used to prevent concurrent
    scans in single-worker mode."""
    row = (
        get_conn()
        .execute(
            "SELECT 1 FROM scan_runs WHERE kind = ? AND status = 'running' LIMIT 1",
            (kind,),
        )
        .fetchone()
    )
    return row is not None
