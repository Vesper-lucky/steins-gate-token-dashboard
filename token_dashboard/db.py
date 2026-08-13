"""SQLite schema, connection, and shared query helpers."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

BEIJING_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = SQLITE_TIMEOUT_SECONDS * 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  path        TEXT PRIMARY KEY,
  mtime       REAL    NOT NULL,
  bytes_read  INTEGER NOT NULL,
  scanned_at  REAL    NOT NULL,
  content_sig TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  uuid                    TEXT PRIMARY KEY,
  parent_uuid             TEXT,
  session_id              TEXT NOT NULL,
  project_slug            TEXT NOT NULL,
  source_path             TEXT,
  cwd                     TEXT,
  git_branch              TEXT,
  cc_version              TEXT,
  entrypoint              TEXT,
  type                    TEXT NOT NULL,
  is_sidechain            INTEGER NOT NULL DEFAULT 0,
  agent_id                TEXT,
  timestamp               TEXT NOT NULL,
  model                   TEXT,
  stop_reason             TEXT,
  prompt_id               TEXT,
  message_id              TEXT,
  event_key               TEXT,
  root_session_id         TEXT,
  parent_session_id       TEXT,
  is_subagent             INTEGER NOT NULL DEFAULT 0,
  thread_depth            INTEGER NOT NULL DEFAULT 0,
  model_calls             INTEGER NOT NULL DEFAULT 0,
  raw_input_tokens        INTEGER NOT NULL DEFAULT 0,
  input_tokens            INTEGER NOT NULL DEFAULT 0,
  output_tokens           INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
  cache_create_5m_tokens  INTEGER NOT NULL DEFAULT 0,
  cache_create_1h_tokens  INTEGER NOT NULL DEFAULT 0,
  prompt_text             TEXT,
  prompt_chars            INTEGER,
  tool_calls_json         TEXT
  ,quality_flags          TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session   ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_project   ON messages(project_slug);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_model     ON messages(model);
CREATE INDEX IF NOT EXISTS idx_messages_msgid     ON messages(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_messages_source    ON messages(source_path);
CREATE INDEX IF NOT EXISTS idx_messages_root      ON messages(root_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_event
  ON messages(root_session_id, type, event_key) WHERE event_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS tool_calls (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  message_uuid  TEXT    NOT NULL,
  session_id    TEXT    NOT NULL,
  project_slug  TEXT    NOT NULL,
  tool_name     TEXT    NOT NULL,
  target        TEXT,
  tool_use_id   TEXT,
  event_key     TEXT,
  result_tokens INTEGER,
  result_estimated INTEGER NOT NULL DEFAULT 0,
  result_unassigned INTEGER NOT NULL DEFAULT 0,
  is_error      INTEGER NOT NULL DEFAULT 0,
  timestamp     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tools_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tools_name    ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tools_target  ON tool_calls(target);
CREATE INDEX IF NOT EXISTS idx_tools_msg     ON tool_calls(message_uuid);
CREATE INDEX IF NOT EXISTS idx_tools_use_id  ON tool_calls(session_id, tool_use_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tools_event
  ON tool_calls(session_id, event_key) WHERE event_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS plan (
  k TEXT PRIMARY KEY,
  v TEXT
);

CREATE TABLE IF NOT EXISTS dismissed_tips (
  tip_key       TEXT PRIMARY KEY,
  dismissed_at  REAL NOT NULL
);
"""


def default_db_path() -> Path:
    return Path.home() / ".claude" / "token-dashboard.db"


def init_db(path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS) as c:
        _configure_connection(c, enable_wal=True)
        _migrate_add_message_id(c)
        _migrate_add_source_tracking(c)
        _migrate_ledger_facts(c)
        c.executescript(SCHEMA)


def _migrate_add_message_id(conn) -> None:
    """Add messages.message_id for streaming-snapshot dedup.

    Why: pre-migration rows were summed from all streaming snapshots (over-count).
    How to apply: if the old table exists without the column, add it and clear
    messages/tool_calls/files so the next scan replays JSONLs cleanly. Source
    of truth is on disk; rescanning is cheap.
    """
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if not has_table:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "message_id" in cols:
        return
    conn.execute("ALTER TABLE messages ADD COLUMN message_id TEXT")
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM tool_calls")
    conn.execute("DELETE FROM files")
    conn.commit()


def _migrate_add_source_tracking(conn) -> None:
    """Track which source file owns each cached row and detect file rewrites."""
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    changed = False
    if "files" in tables:
        file_cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
        if "content_sig" not in file_cols:
            conn.execute("ALTER TABLE files ADD COLUMN content_sig TEXT")
            changed = True
    if "messages" in tables:
        message_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        if "source_path" not in message_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN source_path TEXT")
            changed = True
    if not changed:
        return
    for table in ("tool_calls", "messages", "files"):
        if table in tables:
            conn.execute(f"DELETE FROM {table}")
    conn.commit()


def _migrate_ledger_facts(conn) -> None:
    """Add stable lineage/quality columns and replay facts once.

    Pricing settings and dismissed tips deliberately live outside the fact
    tables and are preserved.
    """
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "messages" not in tables:
        return
    message_columns = {
        "event_key": "TEXT",
        "root_session_id": "TEXT",
        "parent_session_id": "TEXT",
        "is_subagent": "INTEGER NOT NULL DEFAULT 0",
        "thread_depth": "INTEGER NOT NULL DEFAULT 0",
        "model_calls": "INTEGER NOT NULL DEFAULT 0",
        "raw_input_tokens": "INTEGER NOT NULL DEFAULT 0",
        "reasoning_output_tokens": "INTEGER NOT NULL DEFAULT 0",
        "quality_flags": "TEXT",
    }
    tool_columns = {
        "tool_use_id": "TEXT",
        "event_key": "TEXT",
        "result_estimated": "INTEGER NOT NULL DEFAULT 0",
        "result_unassigned": "INTEGER NOT NULL DEFAULT 0",
    }
    existing_messages = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    existing_tools = (
        {row[1] for row in conn.execute("PRAGMA table_info(tool_calls)")}
        if "tool_calls" in tables else set()
    )
    changed = False
    for name, declaration in message_columns.items():
        if name not in existing_messages:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {declaration}")
            changed = True
    if "tool_calls" in tables:
        for name, declaration in tool_columns.items():
            if name not in existing_tools:
                conn.execute(f"ALTER TABLE tool_calls ADD COLUMN {name} {declaration}")
                changed = True
    if changed:
        for table in ("tool_calls", "messages", "files"):
            if table in tables:
                conn.execute(f"DELETE FROM {table}")
        conn.commit()


@contextmanager
def connect(path: Union[str, Path]):
    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    _configure_connection(conn)
    try:
        yield conn
    finally:
        conn.close()


def _configure_connection(conn, enable_wal: bool = False) -> None:
    conn.execute("PRAGMA busy_timeout = %d" % SQLITE_BUSY_TIMEOUT_MS)
    conn.execute("PRAGMA foreign_keys = ON")
    if enable_wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def _range_clause(since, until, col: str = "timestamp"):
    where, args = [], []
    if since:
        where.append(f"{col} >= ?")
        args.append(since)
    if until:
        where.append(f"{col} < ?")
        args.append(until)
    return ((" AND " + " AND ".join(where)) if where else "", args)


def _long_context_sums() -> str:
    """Aggregate token buckets from requests whose total input exceeds 272K."""
    total_input = (
        "input_tokens + cache_read_tokens + "
        "cache_create_5m_tokens + cache_create_1h_tokens"
    )
    columns = []
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_create_5m_tokens",
        "cache_create_1h_tokens",
    ):
        columns.append(
            f"COALESCE(SUM(CASE WHEN {total_input} > 272000 "
            f"THEN {name} ELSE 0 END),0) AS long_context_{name}"
        )
    return ",\n             ".join(columns)


def _pricing_period(cutoffs) -> tuple[str, list]:
    cutoffs = list(cutoffs or [])
    if not cutoffs:
        return "0", []
    cases = " ".join(
        f"WHEN datetime(timestamp) < datetime(?) THEN {index}"
        for index, _ in enumerate(cutoffs)
    )
    return f"CASE {cases} ELSE {len(cutoffs)} END", cutoffs


def _beijing_datetime(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(BEIJING_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=BEIJING_TZ)
    return now.astimezone(BEIJING_TZ)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _encode_slug(path: str) -> str:
    """Claude Code's project-slug encoding: each of `:`, `\\`, `/`, space → one `-`."""
    return re.sub(r"[:\\/ ]", "-", path)


def _walk_to_root(cwd: str, slug: str) -> Optional[str]:
    """If any ancestor of cwd encodes to slug, return that ancestor's basename."""
    if not cwd or not slug:
        return None
    trimmed = cwd.rstrip("/\\")
    sep = "\\" if "\\" in trimmed else "/"
    parts = trimmed.split(sep)
    for i in range(len(parts), 0, -1):
        if _encode_slug(sep.join(parts[:i])) == slug:
            name = parts[i - 1]
            if name:
                return name
    return None


def project_name_for(cwd: Optional[str], fallback_slug: str) -> str:
    """Pretty project name from a single cwd + slug (best-effort).

    For the multi-cwd case, prefer `best_project_name`.
    """
    name = _walk_to_root(cwd or "", fallback_slug or "")
    if name:
        return name
    if cwd:
        trimmed = cwd.rstrip("/\\")
        sep = "\\" if "\\" in trimmed else "/"
        tail = trimmed.split(sep)[-1]
        if tail:
            return tail
    if fallback_slug:
        parts = [p for p in re.split(r"-+", fallback_slug) if p]
        if parts:
            return parts[-1]
    return fallback_slug or ""


def best_project_name(cwds, slug: str) -> str:
    """Pick a pretty name from a list of cwds.

    Prefer a cwd whose walk-up matches `slug` (a true descendant of the project
    root). If none match, fall back to `project_name_for` on the first cwd,
    then to the slug's last segment.
    """
    cwds = [c for c in (cwds or []) if c]
    for cwd in cwds:
        name = _walk_to_root(cwd, slug)
        if name:
            return name
    return project_name_for(cwds[0] if cwds else None, slug)


def overview_totals(db_path, since=None, until=None) -> dict:
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT COUNT(DISTINCT session_id) AS sessions,
             COUNT(DISTINCT COALESCE(root_session_id,session_id)) AS root_sessions,
             COUNT(DISTINCT CASE WHEN COALESCE(is_subagent,0)=1 THEN session_id END) AS subagent_sessions,
             COALESCE(SUM(CASE WHEN type='user' THEN 1 ELSE 0 END),0) AS turns,
             COALESCE(SUM(CASE WHEN type='assistant' THEN CASE
               WHEN model_calls>0 THEN model_calls
               WHEN input_tokens+output_tokens+cache_read_tokens
                 +cache_create_5m_tokens+cache_create_1h_tokens>0 THEN 1 ELSE 0 END
               ELSE 0 END),0) AS model_calls,
             COALESCE(SUM(input_tokens),0)            AS input_tokens,
             COALESCE(SUM(output_tokens),0)           AS output_tokens,
             COALESCE(SUM(reasoning_output_tokens),0) AS reasoning_output_tokens,
             COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
             COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens,
             COALESCE(SUM(input_tokens),0)
               + COALESCE(SUM(cache_read_tokens),0)
               + COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS total_input_tokens
        FROM messages WHERE 1=1 {rng}
    """
    with connect(db_path) as c:
        return dict(c.execute(sql, args).fetchone())


def token_duo_total_tokens(db_path, since=None, until=None) -> int:
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT COALESCE(SUM(input_tokens),0)
               + COALESCE(SUM(output_tokens),0)
               + COALESCE(SUM(cache_read_tokens),0)
               + COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS total_tokens
        FROM messages WHERE 1=1 {rng}
    """
    with connect(db_path) as c:
        row = c.execute(sql, args).fetchone()
        return int(row["total_tokens"] or 0)


def expensive_prompts(db_path, limit: int = 50, sort: str = "tokens") -> list:
    """User prompt joined with the immediately-following assistant turn's tokens.

    sort="tokens" (default) → largest billable first.
    sort="recent"           → newest first.
    """
    sql = """
      SELECT u.uuid AS user_uuid, u.session_id, u.project_slug, u.timestamp,
             u.prompt_text, u.prompt_chars,
             a.uuid AS assistant_uuid, COALESCE(a.model,'unknown') AS model,
             a.timestamp AS pricing_at,
             COALESCE(a.input_tokens,0) AS input_tokens,
             COALESCE(a.output_tokens,0) AS output_tokens,
             COALESCE(a.cache_read_tokens,0) AS cache_read_tokens,
             COALESCE(a.cache_create_5m_tokens,0) AS cache_create_5m_tokens,
             COALESCE(a.cache_create_1h_tokens,0) AS cache_create_1h_tokens
        FROM messages u
        JOIN messages a ON a.parent_uuid = u.uuid AND a.type='assistant'
       WHERE u.type='user' AND u.prompt_text IS NOT NULL
       ORDER BY u.timestamp DESC, a.timestamp ASC
    """
    with connect(db_path) as c:
        source = [dict(r) for r in c.execute(sql)]
    grouped = {}
    for row in source:
        item = grouped.setdefault(row["user_uuid"], {
            key: row[key] for key in (
                "user_uuid", "session_id", "project_slug", "timestamp",
                "prompt_text", "prompt_chars", "assistant_uuid", "model",
            )
        })
        item.setdefault("pricing_segments", []).append({
            key: row[key] for key in (
                "model", "pricing_at", "input_tokens", "output_tokens",
                "cache_read_tokens", "cache_create_5m_tokens", "cache_create_1h_tokens",
            )
        })
        for key in (
            "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_create_5m_tokens", "cache_create_1h_tokens",
        ):
            item[key] = item.get(key, 0) + row[key]
        item["billable_tokens"] = sum(
            item[key] for key in (
                "input_tokens", "output_tokens", "cache_read_tokens",
                "cache_create_5m_tokens", "cache_create_1h_tokens",
            )
        )
        if item["model"] != row["model"]:
            item["model"] = "multiple"
    rows = list(grouped.values())
    if sort == "recent":
        rows.sort(key=lambda row: row["timestamp"], reverse=True)
    else:
        rows.sort(key=lambda row: row["billable_tokens"], reverse=True)
    return rows[:limit]


def project_summary(db_path, since=None, until=None) -> list:
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT project_slug,
             COUNT(DISTINCT session_id) AS sessions,
             SUM(CASE WHEN type='user' THEN 1 ELSE 0 END) AS turns,
             COALESCE(SUM(input_tokens), 0)  AS input_tokens,
             COALESCE(SUM(output_tokens), 0) AS output_tokens,
             COALESCE(SUM(input_tokens),0)+COALESCE(SUM(output_tokens),0)
               +COALESCE(SUM(cache_read_tokens),0)
               +COALESCE(SUM(cache_create_5m_tokens),0)+COALESCE(SUM(cache_create_1h_tokens),0) AS billable_tokens,
             COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,
             COALESCE(SUM(input_tokens),0)+COALESCE(SUM(output_tokens),0)
               +COALESCE(SUM(cache_read_tokens),0)
               +COALESCE(SUM(cache_create_5m_tokens),0)+COALESCE(SUM(cache_create_1h_tokens),0) AS total_tokens
        FROM messages m
       WHERE 1=1 {rng}
       GROUP BY project_slug
       ORDER BY billable_tokens DESC
    """
    with connect(db_path) as c:
        rows = [dict(r) for r in c.execute(sql, args)]
        for r in rows:
            cwds = [row["cwd"] for row in c.execute(
                "SELECT DISTINCT cwd FROM messages WHERE project_slug=? AND cwd IS NOT NULL",
                (r["project_slug"],),
            )]
            r["project_name"] = best_project_name(cwds, r["project_slug"])
    return rows


def project_model_breakdown(db_path, since=None, until=None, pricing_cutoffs=None) -> list:
    """Per-project, per-model token totals. Caller computes cost via pricing."""
    rng, args = _range_clause(since, until)
    period_sql, period_args = _pricing_period(pricing_cutoffs)
    sql = f"""
      SELECT project_slug,
             COALESCE(model, 'unknown') AS model,
             {period_sql} AS pricing_period,
             MIN(timestamp) AS pricing_at,
             COALESCE(SUM(input_tokens),0)            AS input_tokens,
             COALESCE(SUM(output_tokens),0)           AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
             COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens,
             COALESCE(SUM(reasoning_output_tokens),0) AS reasoning_output_tokens,
             {_long_context_sums()}
        FROM messages
       WHERE type = 'assistant' {rng}
       GROUP BY project_slug, model, pricing_period
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, (*period_args, *args))]


def tool_token_breakdown(db_path, since=None, until=None) -> list:
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT tool_name,
             COUNT(*) AS calls,
             COALESCE(SUM(result_tokens),0) AS result_tokens,
             1 AS result_tokens_estimated
        FROM tool_calls
       WHERE tool_name != '_tool_result' {rng}
       GROUP BY tool_name
       ORDER BY calls DESC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, args)]


def recent_sessions(db_path, limit: int = 20, since=None, until=None) -> list:
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT session_id, project_slug,
             MIN(timestamp) AS started, MAX(timestamp) AS ended,
             SUM(CASE WHEN type='user' THEN 1 ELSE 0 END) AS turns,
             COALESCE(SUM(CASE WHEN type='assistant' THEN CASE
               WHEN model_calls>0 THEN model_calls
               WHEN input_tokens+output_tokens+cache_read_tokens
                 +cache_create_5m_tokens+cache_create_1h_tokens>0 THEN 1 ELSE 0 END
               ELSE 0 END),0) AS model_calls,
             COALESCE(SUM(input_tokens),0)
               + COALESCE(SUM(output_tokens),0)
               + COALESCE(SUM(cache_read_tokens),0)
               + COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS tokens
        FROM messages m
       WHERE 1=1 {rng}
       GROUP BY session_id
       ORDER BY ended DESC
       LIMIT ?
    """
    with connect(db_path) as c:
        rows = [dict(r) for r in c.execute(sql, (*args, limit))]
        # Cache per-slug name lookups so we don't query once per session.
        slug_cache = {}
        for r in rows:
            slug = r["project_slug"]
            if slug not in slug_cache:
                cwds = [row["cwd"] for row in c.execute(
                    "SELECT DISTINCT cwd FROM messages WHERE project_slug=? AND cwd IS NOT NULL",
                    (slug,),
                )]
                slug_cache[slug] = best_project_name(cwds, slug)
            r["project_name"] = slug_cache[slug]
    return rows


def session_turns(db_path, session_id: str) -> list:
    sql = """
      SELECT uuid, parent_uuid, type, timestamp, model, is_sidechain, agent_id,
             input_tokens, output_tokens, cache_read_tokens,
             cache_create_5m_tokens, cache_create_1h_tokens,
             reasoning_output_tokens, model_calls, root_session_id,
             parent_session_id, is_subagent, thread_depth,
             prompt_text, prompt_chars, tool_calls_json, project_slug, cwd
        FROM messages
       WHERE session_id = ?
       ORDER BY timestamp ASC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, (session_id,))]


def daily_token_breakdown(db_path, since=None, until=None) -> list:
    """One Beijing-calendar row per day for the overview charts."""
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT strftime('%Y-%m-%d', timestamp, '+8 hours') AS day,
             COALESCE(SUM(input_tokens),0)      AS input_tokens,
             COALESCE(SUM(output_tokens),0)     AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS cache_create_tokens,
             COALESCE(SUM(input_tokens),0)
               + COALESCE(SUM(cache_read_tokens),0)
               + COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS total_input_tokens
        FROM messages
       WHERE timestamp IS NOT NULL {rng}
       GROUP BY day
       ORDER BY day ASC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, args)]


def daily_model_token_breakdown(db_path, since=None, until=None, pricing_cutoffs=None) -> list:
    """One Beijing-calendar row per day and model for cost estimates."""
    rng, args = _range_clause(since, until)
    period_sql, period_args = _pricing_period(pricing_cutoffs)
    sql = f"""
      SELECT strftime('%Y-%m-%d', timestamp, '+8 hours') AS day,
             COALESCE(model, 'unknown') AS model,
             {period_sql} AS pricing_period,
             MIN(timestamp) AS pricing_at,
             COALESCE(SUM(input_tokens),0)            AS input_tokens,
             COALESCE(SUM(output_tokens),0)           AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
             COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens,
             COALESCE(SUM(reasoning_output_tokens),0) AS reasoning_output_tokens,
             {_long_context_sums()}
        FROM messages
       WHERE type = 'assistant' AND timestamp IS NOT NULL {rng}
       GROUP BY day, model, pricing_period
       ORDER BY day ASC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, (*period_args, *args))]


def today_hourly_token_breakdown(db_path, now: Optional[datetime] = None) -> list:
    """24 hourly rows for today's usage using Beijing time (UTC+08:00)."""
    start_local = _beijing_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    since = _utc_iso(start_local)
    until = _utc_iso(end_local)
    sql = """
      SELECT CAST(strftime('%H', timestamp, '+8 hours') AS INTEGER) AS hour_index,
             COALESCE(SUM(input_tokens),0)      AS input_tokens,
             COALESCE(SUM(output_tokens),0)     AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS cache_create_tokens,
             COALESCE(SUM(input_tokens),0)
               + COALESCE(SUM(cache_read_tokens),0)
               + COALESCE(SUM(cache_create_5m_tokens),0)
               + COALESCE(SUM(cache_create_1h_tokens),0) AS total_input_tokens
        FROM messages
       WHERE timestamp IS NOT NULL
         AND datetime(timestamp) >= datetime(?)
         AND datetime(timestamp) < datetime(?)
       GROUP BY hour_index
       ORDER BY hour_index ASC
    """
    with connect(db_path) as c:
        by_hour = {int(r["hour_index"]): dict(r) for r in c.execute(sql, (since, until))}
    rows = []
    for hour in range(24):
        r = by_hour.get(hour, {})
        rows.append({
            "hour": f"{hour:02d}:00",
            "hour_index": hour,
            "input_tokens": r.get("input_tokens", 0),
            "output_tokens": r.get("output_tokens", 0),
            "cache_read_tokens": r.get("cache_read_tokens", 0),
            "cache_create_tokens": r.get("cache_create_tokens", 0),
            "total_input_tokens": r.get("total_input_tokens", 0),
        })
    return rows


def today_hourly_model_token_breakdown(
    db_path, now: Optional[datetime] = None, pricing_cutoffs=None
) -> list:
    """One row per Beijing-hour and model for today's period-level costs."""
    start_local = _beijing_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    since = _utc_iso(start_local)
    until = _utc_iso(end_local)
    period_sql, period_args = _pricing_period(pricing_cutoffs)
    sql = f"""
      SELECT CAST(strftime('%H', timestamp, '+8 hours') AS INTEGER) AS hour_index,
             COALESCE(model, 'unknown') AS model,
             {period_sql} AS pricing_period,
             MIN(timestamp) AS pricing_at,
             COALESCE(SUM(input_tokens),0)            AS input_tokens,
             COALESCE(SUM(output_tokens),0)           AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
             COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens,
             COALESCE(SUM(reasoning_output_tokens),0) AS reasoning_output_tokens,
             {_long_context_sums()}
        FROM messages
       WHERE type = 'assistant'
         AND timestamp IS NOT NULL
         AND datetime(timestamp) >= datetime(?)
         AND datetime(timestamp) < datetime(?)
       GROUP BY hour_index, model, pricing_period
       ORDER BY hour_index ASC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, (*period_args, since, until))]


def skill_breakdown(db_path, since=None, until=None) -> list:
    """Per-skill invocation counts, distinct sessions, last-used timestamp.

    Token attribution per skill is not included: in Claude Code, a Skill's
    content is loaded via a system-reminder on the next turn, not as the
    tool_result body — so `result_tokens` on _tool_result rows reflects the
    activation ack (tiny), not the skill definition (which is what actually
    fills context). A future schema change (storing tool_use_id on the
    invocation row) could enable precise attribution; for now we only expose
    the reliable counts.
    """
    rng, args = _range_clause(since, until)
    sql = f"""
      SELECT target AS skill,
             COUNT(*) AS invocations,
             COUNT(DISTINCT session_id) AS sessions,
             MAX(timestamp) AS last_used
        FROM tool_calls
       WHERE tool_name = 'Skill' AND target IS NOT NULL AND target != '' {rng}
       GROUP BY target
       ORDER BY invocations DESC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, args)]


def model_breakdown(db_path, since=None, until=None, pricing_cutoffs=None) -> list:
    """Per-model token totals + turn count. Caller computes cost via pricing."""
    rng, args = _range_clause(since, until)
    period_sql, period_args = _pricing_period(pricing_cutoffs)
    sql = f"""
      SELECT COALESCE(model, 'unknown') AS model,
             {period_sql} AS pricing_period,
             MIN(timestamp) AS pricing_at,
             COALESCE(SUM(CASE WHEN model_calls>0 THEN model_calls
               WHEN input_tokens+output_tokens+cache_read_tokens
                 +cache_create_5m_tokens+cache_create_1h_tokens>0 THEN 1 ELSE 0 END),0) AS turns,
             COALESCE(SUM(input_tokens),0)            AS input_tokens,
             COALESCE(SUM(output_tokens),0)           AS output_tokens,
             COALESCE(SUM(cache_read_tokens),0)       AS cache_read_tokens,
             COALESCE(SUM(cache_create_5m_tokens),0)  AS cache_create_5m_tokens,
             COALESCE(SUM(cache_create_1h_tokens),0)  AS cache_create_1h_tokens,
             COALESCE(SUM(reasoning_output_tokens),0) AS reasoning_output_tokens,
             {_long_context_sums()}
        FROM messages
       WHERE type = 'assistant' {rng}
       GROUP BY model, pricing_period
       ORDER BY (input_tokens + output_tokens + cache_read_tokens
                 + cache_create_5m_tokens + cache_create_1h_tokens) DESC
    """
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(sql, (*period_args, *args))]


def data_quality(db_path, bridge_roots=None) -> dict:
    with connect(db_path) as c:
        db = dict(c.execute("""
          SELECT COUNT(*) AS messages,
                 COUNT(DISTINCT CASE WHEN type='assistant' AND model_calls>0 THEN event_key END) AS unique_model_events,
                 COALESCE(SUM(model_calls),0) AS model_calls,
                 SUM(CASE WHEN cc_version='codex-bridge' THEN 1 ELSE 0 END) AS bridge_messages,
                 COALESCE(SUM(input_tokens+cache_read_tokens+cache_create_5m_tokens
                   +cache_create_1h_tokens),0) AS input_bucket_total
            FROM messages
        """).fetchone())
        db["tool_calls"] = c.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE tool_name NOT IN ('_tool_result','_unallocated')"
        ).fetchone()[0]
        db["unallocated_tool_results"] = c.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE result_unassigned=1"
        ).fetchone()[0]
        db["duplicate_message_event_keys"] = c.execute("""
          SELECT COUNT(*) FROM (
            SELECT root_session_id,type,event_key FROM messages
             WHERE event_key IS NOT NULL GROUP BY root_session_id,type,event_key HAVING COUNT(*)>1
          )
        """).fetchone()[0]
        db["input_conservation_deviation"] = c.execute("""
          SELECT COALESCE(SUM(ABS(raw_input_tokens-input_tokens-cache_read_tokens
            -cache_create_5m_tokens-cache_create_1h_tokens)),0)
            FROM messages WHERE type='assistant'
        """).fetchone()[0]
    manifests = []
    for root in bridge_roots or []:
        path = Path(root) / ".codex_bridge_state.json"
        try:
            state = __import__("json").loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        manifests.append({"path": str(path), **(state.get("quality") or {})})
    expected_records = sum(item.get("accepted_events", 0) for item in manifests)
    warnings = []
    notices = []
    errors = []
    if db["duplicate_message_event_keys"]:
        errors.append("数据库存在重复稳定事件键")
    if db["input_conservation_deviation"]:
        errors.append("数据库输入 token 分桶不守恒")
    if expected_records and expected_records != (db["bridge_messages"] or 0):
        errors.append("bridge manifest 与数据库消息数不一致")
    for item in manifests:
        if item.get("damaged_lines"):
            notices.append(f"bridge 已跳过 {item['damaged_lines']} 条无法解析的历史日志行")
        if item.get("read_errors"):
            warnings.append("bridge 读取源日志失败")
        if item.get("unknown_tool_types"):
            warnings.append("bridge 发现未知工具类型")
        if item.get("bucket_corrections"):
            warnings.append("bridge 修正了超出原始 input 的缓存桶")
    return {
        "ok": not errors,
        "database": db,
        "bridge_manifests": manifests,
        "manifest_accepted_events": expected_records,
        "warnings": warnings,
        "notices": notices,
        "errors": errors,
    }
