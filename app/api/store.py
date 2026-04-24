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
_tls = threading.local()
_migrate_lock = threading.Lock()
_migrated = False


def _open_conn() -> sqlite3.Connection:
    """Open a fresh SQLite connection with MetaSift's pragmas. Callers get a
    private handle — no sharing across threads, no internal-mutex contention,
    no explicit-transaction bleed from one caller into another.

    WAL mode + per-thread connections is SQLite's supported concurrency path:
    many readers proceed in parallel, one writer blocks only other writers,
    and no Python-level lock is needed to coordinate."""
    path = api_settings.sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,  # autocommit; we manage explicit transactions
        timeout=30.0,  # wait up to 30s for a writer to release before SQLITE_BUSY
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def get_conn() -> sqlite3.Connection:
    """Return this thread's SQLite connection, opening one on first call.

    Previously a single connection was shared across every thread in the
    process. That guaranteed cross-thread contention on sqlite3's internal
    mutex — a scan worker running an explicit BEGIN/COMMIT could freeze the
    event loop while it held the connection for a slow LLM call. Per-thread
    connections eliminate that failure mode outright.
    """
    apply_migrations()
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = _open_conn()
        _tls.conn = conn
    return conn


def apply_migrations() -> None:
    """Run any pending .sql files once per process. Guarded by a lock so two
    threads that hit a fresh process (e.g. startup + first request racing)
    don't both try to apply the same migrations."""
    global _migrated
    if _migrated:
        return
    with _migrate_lock:
        if _migrated:
            return
        conn = _open_conn()
        try:
            _run_migrations(conn)
        finally:
            conn.close()
        _migrated = True


def _run_migrations(conn: sqlite3.Connection) -> None:
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
        # `executescript` implicitly COMMITs any pending transaction first, so
        # wrapping it in a BEGIN/COMMIT here would be a no-op at best and a
        # double-commit error at worst. Autocommit-per-statement is fine for
        # one-time schema DDL.
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


def try_start_scan(kind: str) -> int | None:
    """Atomically claim a scan slot. Returns a fresh run_id if no other run of
    this kind is currently `running`, else None. Closes the TOCTOU gap that
    `scan_is_running(...)` + `start_scan(...)` leaves open when two requests
    race on the same kind.

    `BEGIN IMMEDIATE` takes the write lock up front so the SELECT sees the
    latest committed state across per-thread connections. With `BEGIN
    DEFERRED` (the sqlite default), two threads could both read "nothing
    running" from their own snapshots and both INSERT — the shared-connection
    era hid this accidentally via the Python sqlite3 mutex.
    """
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT 1 FROM scan_runs WHERE kind = ? AND status = 'running' LIMIT 1",
            (kind,),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return None
        cur = conn.execute(
            "INSERT INTO scan_runs (kind, status) VALUES (?, 'running')",
            (kind,),
        )
        conn.execute("COMMIT")
        return cur.lastrowid or 0
    except Exception:
        conn.execute("ROLLBACK")
        raise


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


def reap_zombie_scans() -> int:
    """Mark any `status='running'` rows that outlived the process as failed.

    When uvicorn crashes or is killed mid-scan, the `scan_runs` row never
    gets its `finished_at` / `status` update. On next boot, `try_start_scan`
    sees it as still-running and blocks new runs of that kind until the user
    hits the DB manually. This reaper sweeps those zombies at startup so the
    first post-restart request works.

    Returns the number of rows reaped — used by callers (lifespan) to log.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE scan_runs SET finished_at = ?, status = 'failed', "
            "error = 'Reaped on startup — process died before scan finished' "
            "WHERE status = 'running'",
            (datetime.now(UTC).isoformat(),),
        )
        return cur.rowcount or 0


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
