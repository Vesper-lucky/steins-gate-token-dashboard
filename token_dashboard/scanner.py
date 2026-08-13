"""JSONL transcript walker + parser."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from .db import connect
from .locking import AlreadyRunning, process_lock


INSERT_MSG = """
INSERT OR REPLACE INTO messages (
  uuid, parent_uuid, session_id, project_slug, source_path, cwd, git_branch, cc_version, entrypoint,
  type, is_sidechain, agent_id, timestamp, model, stop_reason, prompt_id, message_id,
  event_key, root_session_id, parent_session_id, is_subagent, thread_depth, model_calls,
  raw_input_tokens,
  input_tokens, output_tokens, cache_read_tokens, cache_create_5m_tokens, cache_create_1h_tokens,
  reasoning_output_tokens,
  prompt_text, prompt_chars, tool_calls_json, quality_flags
) VALUES (
  :uuid, :parent_uuid, :session_id, :project_slug, :source_path, :cwd, :git_branch, :cc_version, :entrypoint,
  :type, :is_sidechain, :agent_id, :timestamp, :model, :stop_reason, :prompt_id, :message_id,
  :event_key, :root_session_id, :parent_session_id, :is_subagent, :thread_depth, :model_calls,
  :raw_input_tokens,
  :input_tokens, :output_tokens, :cache_read_tokens, :cache_create_5m_tokens, :cache_create_1h_tokens,
  :reasoning_output_tokens,
  :prompt_text, :prompt_chars, :tool_calls_json, :quality_flags
)
"""

INSERT_TOOL = """
INSERT OR IGNORE INTO tool_calls (
  message_uuid, session_id, project_slug, tool_name, target, tool_use_id, event_key,
  result_tokens, result_estimated, result_unassigned, is_error, timestamp
) VALUES (
  :message_uuid, :session_id, :project_slug, :tool_name, :target, :tool_use_id, :event_key,
  :result_tokens, :result_estimated, :result_unassigned, :is_error, :timestamp
)
"""


_TARGET_FIELDS = {
    "Read":      "file_path",
    "Edit":      "file_path",
    "Write":     "file_path",
    "Glob":      "pattern",
    "Grep":      "pattern",
    "Bash":      "command",
    "WebFetch":  "url",
    "WebSearch": "query",
    "Task":      "subagent_type",
    "Skill":     "skill",
}
_SIGNATURE_CHUNK_BYTES = 65536


def _usage(rec: dict) -> dict:
    u = (rec.get("message") or {}).get("usage") or {}
    cc = u.get("cache_creation") or {}
    return {
        "input_tokens":           int(u.get("input_tokens") or 0),
        "output_tokens":          int(u.get("output_tokens") or 0),
        "cache_read_tokens":      int(u.get("cache_read_input_tokens") or 0),
        "cache_create_5m_tokens": int(cc.get("ephemeral_5m_input_tokens") or 0),
        "cache_create_1h_tokens": int(cc.get("ephemeral_1h_input_tokens") or 0),
        "reasoning_output_tokens": int(u.get("reasoning_output_tokens") or 0),
    }


def _prompt_text(rec: dict) -> Tuple[Optional[str], Optional[int]]:
    if rec.get("type") != "user":
        return None, None
    content = (rec.get("message") or {}).get("content")
    explicit_chars = (rec.get("message") or {}).get("prompt_chars")
    if isinstance(explicit_chars, int):
        return "[prompt omitted by divergence-ledger]", max(explicit_chars, 0)
    if isinstance(content, str):
        return content, len(content)
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        text = "".join(parts) if parts else None
        return text, (len(text) if text else None)
    return None, None


def _target(name: str, inp: dict) -> Optional[str]:
    field = _TARGET_FIELDS.get(name)
    if field and isinstance(inp, dict):
        v = inp.get(field)
        if isinstance(v, str):
            return v[:500]
    return None


def _extract_tools(rec: dict) -> List[dict]:
    out = []
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name") or "unknown"
        target = _target(name, block.get("input") or {})
        out.append({
            "tool_name":     name,
            "target":        target,
            "tool_use_id":   block.get("id"),
            "event_key":     block.get("event_key") or (f"tool:{block.get('id')}" if block.get("id") else None),
            "result_tokens": None,
            "result_estimated": 0,
            "result_unassigned": 0,
            "is_error":      0,
            "timestamp":     rec.get("timestamp"),
        })
    return out


def _content_chars(value) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_content_chars(item) for item in value)
    if isinstance(value, dict):
        return sum(_content_chars(key) + _content_chars(item) for key, item in value.items())
    return 0


def _extract_results(rec: dict) -> List[dict]:
    out = []
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        body = block.get("content")
        if isinstance(block.get("result_tokens"), int):
            tokens = max(block["result_tokens"], 0)
        elif isinstance(body, (str, list, dict)):
            tokens = _content_chars(body) // 4
        else:
            tokens = 0
        out.append({
            "tool_name":     "_tool_result",
            "target":        block.get("tool_use_id"),
            "tool_use_id":   block.get("tool_use_id"),
            "event_key":     block.get("event_key") or (f"result:{block.get('tool_use_id')}" if block.get("tool_use_id") else None),
            "result_tokens": tokens,
            "result_estimated": 1 if block.get("result_estimated", True) else 0,
            "result_unassigned": 0,
            "is_error":      1 if block.get("is_error") else 0,
            "timestamp":     rec.get("timestamp"),
        })
    return out


def parse_record(rec: dict, project_slug: str) -> Tuple[dict, List[dict]]:
    """Return (message_row, [tool_call_rows])."""
    msg_obj = rec.get("message") or {}
    text, chars = _prompt_text(rec)
    usage = _usage(rec)
    msg = {
        "uuid":         rec.get("uuid"),
        "parent_uuid":  rec.get("parentUuid"),
        "session_id":   rec.get("sessionId"),
        "project_slug": project_slug,
        "source_path":  None,
        "cwd":          rec.get("cwd"),
        "git_branch":   rec.get("gitBranch"),
        "cc_version":   rec.get("version"),
        "entrypoint":   rec.get("entrypoint"),
        "type":         rec.get("type"),
        "is_sidechain": 1 if rec.get("isSidechain") else 0,
        "agent_id":     rec.get("agentId"),
        "timestamp":    rec.get("timestamp"),
        "model":        msg_obj.get("model"),
        "stop_reason":  msg_obj.get("stop_reason"),
        "prompt_id":    rec.get("promptId"),
        "message_id":   msg_obj.get("id"),
        "event_key":    rec.get("eventKey"),
        "root_session_id": rec.get("rootSessionId") or rec.get("sessionId"),
        "parent_session_id": rec.get("parentSessionId"),
        "is_subagent":  1 if rec.get("isSubagent") else 0,
        "thread_depth": int(rec.get("threadDepth") or 0),
        "model_calls":  1 if rec.get("type") == "assistant" and any(usage.values()) else 0,
        "raw_input_tokens": int(msg_obj.get("usage", {}).get("original_input_tokens") or (
            usage["input_tokens"] + usage["cache_read_tokens"]
            + usage["cache_create_5m_tokens"] + usage["cache_create_1h_tokens"]
        )),
        "prompt_text":  text,
        "prompt_chars": chars,
        "tool_calls_json": None,
        "quality_flags": json.dumps(rec.get("qualityFlags") or []),
        **usage,
    }
    tools = _extract_tools(rec)
    tools.extend(_extract_results(rec))
    if tools:
        msg["tool_calls_json"] = json.dumps(
            [{"name": t["tool_name"], "target": t["target"]} for t in tools if t["tool_name"] != "_tool_result"]
        )
    for t in tools:
        t["message_uuid"] = msg["uuid"]
        t["session_id"]   = msg["session_id"]
        t["project_slug"] = project_slug
    return msg, tools


def _store_tools(conn, tools: List[dict]) -> int:
    stored = 0
    invocations = [tool for tool in tools if tool["tool_name"] != "_tool_result"]
    results = [tool for tool in tools if tool["tool_name"] == "_tool_result"]
    for tool in invocations:
        conn.execute(INSERT_TOOL, tool)
        stored += 1
    for result in results:
        if result.get("event_key") and conn.execute(
            "SELECT 1 FROM tool_calls WHERE session_id=? AND event_key=?",
            (result["session_id"], result["event_key"]),
        ).fetchone():
            continue
        call_id = result.get("tool_use_id")
        matched = False
        if call_id:
            row = conn.execute(
                "SELECT id FROM tool_calls WHERE session_id=? AND tool_use_id=? "
                "AND tool_name!='_tool_result' ORDER BY id DESC LIMIT 1",
                (result["session_id"], call_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE tool_calls SET result_tokens=COALESCE(result_tokens,0)+?, "
                    "result_estimated=MAX(result_estimated,?), is_error=MAX(is_error,?) WHERE id=?",
                    (result["result_tokens"], result["result_estimated"], result["is_error"], row["id"]),
                )
                matched = True
        if not matched:
            result["tool_name"] = "_unallocated"
            result["result_unassigned"] = 1
        conn.execute(INSERT_TOOL, result)
        stored += 1
    return stored


def _project_slug(file_path: Path, projects_root: Path) -> str:
    rel = file_path.relative_to(projects_root)
    return rel.parts[0]


def _evict_prior_snapshots(conn, session_id: str, message_id: str, keep_uuid: str) -> None:
    """Remove older streaming snapshots for the same (session_id, message_id).

    Claude Code writes 2–3 JSONL lines per assistant response (partial → final)
    with identical message.id but distinct top-level uuids. Only the final
    tally matches billing, so earlier snapshots must be replaced, not summed.
    """
    old = [r[0] for r in conn.execute(
        "SELECT uuid FROM messages WHERE session_id=? AND message_id=? AND uuid!=?",
        (session_id, message_id, keep_uuid),
    )]
    if not old:
        return
    placeholders = ",".join("?" * len(old))
    conn.execute(f"DELETE FROM tool_calls WHERE message_uuid IN ({placeholders})", old)
    conn.execute(f"DELETE FROM messages WHERE uuid IN ({placeholders})", old)


def _evict_prior_event(conn, msg: dict) -> None:
    if not msg.get("event_key"):
        return
    old = conn.execute(
        "SELECT uuid FROM messages WHERE root_session_id=? AND type=? AND event_key=? AND uuid!=?",
        (msg["root_session_id"], msg["type"], msg["event_key"], msg["uuid"]),
    ).fetchone()
    if not old:
        return
    conn.execute("DELETE FROM tool_calls WHERE message_uuid=?", (old["uuid"],))
    conn.execute("DELETE FROM messages WHERE uuid=?", (old["uuid"],))


def _prefix_signature(path: Path, length: int) -> str:
    """Fingerprint the complete already-scanned file prefix."""
    size = max(0, min(length, path.stat().st_size))
    digest = hashlib.sha256(str(size).encode("ascii"))
    with open(path, "rb") as handle:
        remaining = size
        while remaining:
            chunk = handle.read(min(remaining, _SIGNATURE_CHUNK_BYTES))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _remove_source_rows(conn, source_path: str) -> None:
    conn.execute(
        "DELETE FROM tool_calls WHERE message_uuid IN "
        "(SELECT uuid FROM messages WHERE source_path=?)",
        (source_path,),
    )
    conn.execute("DELETE FROM messages WHERE source_path=?", (source_path,))


def _is_under_root(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def scan_file(path: Path, project_slug: str, conn, start_byte: int = 0) -> dict:
    """Ingest new lines from a JSONL file starting at ``start_byte``.

    Returns message/tool counts plus ``end_offset`` — the byte offset just
    past the last fully-parsed line. Callers persist ``end_offset`` as the
    file's high-water mark so a line partially flushed at EOF gets re-read
    once it completes.
    """
    msgs = tools = 0
    end_offset = start_byte
    with open(path, "rb") as fb:
        if start_byte:
            fb.seek(start_byte)
        while True:
            raw = fb.readline()
            if not raw:
                break  # EOF
            if not raw.endswith(b"\n"):
                # Partial line — Claude Code is mid-flush. Leave the
                # high-water mark behind the line start so we re-read it
                # once the write completes.
                break
            line_end = fb.tell()
            try:
                line = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                end_offset = line_end
                continue
            if not line:
                end_offset = line_end
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                end_offset = line_end
                continue
            if not isinstance(rec, dict) or "uuid" not in rec or "type" not in rec:
                end_offset = line_end
                continue
            msg, tlist = parse_record(rec, project_slug)
            if not msg["session_id"] or not msg["timestamp"]:
                end_offset = line_end
                continue
            msg["source_path"] = str(path)
            _evict_prior_event(conn, msg)
            if msg["message_id"]:
                _evict_prior_snapshots(conn, msg["session_id"], msg["message_id"], msg["uuid"])
            conn.execute(INSERT_MSG, msg)
            # tool_calls has no natural unique key; clear any prior rows for
            # this uuid so full rescans stay idempotent instead of
            # duplicating rows.
            conn.execute("DELETE FROM tool_calls WHERE message_uuid=?", (msg["uuid"],))
            tools += _store_tools(conn, tlist)
            msgs += 1
            end_offset = line_end
    return {"messages": msgs, "tools": tools, "end_offset": end_offset}


def scan_dir(projects_root: Union[str, Path], db_path: Union[str, Path]) -> dict:
    root = Path(projects_root)
    totals = {"messages": 0, "tools": 0, "files": 0}
    if not root.is_dir():
        return totals
    paths = list(root.rglob("*.jsonl"))
    current_paths = {str(path) for path in paths}
    with connect(db_path) as conn:
        known_paths = {
            row["path"] for row in conn.execute("SELECT path FROM files")
            if _is_under_root(row["path"], root)
        }
        for missing_path in known_paths - current_paths:
            _remove_source_rows(conn, missing_path)
            conn.execute("DELETE FROM files WHERE path=?", (missing_path,))
        if known_paths - current_paths:
            conn.commit()

        for p in paths:
            try:
                stat = p.stat()
            except OSError:
                continue
            row = conn.execute(
                "SELECT mtime, bytes_read, content_sig FROM files WHERE path=?", (str(p),)
            ).fetchone()
            offset = 0
            if row and row["mtime"] == stat.st_mtime and row["bytes_read"] == stat.st_size:
                continue
            if row:
                prefix_unchanged = (
                    stat.st_size > row["bytes_read"]
                    and row["content_sig"]
                    and _prefix_signature(p, row["bytes_read"]) == row["content_sig"]
                )
                if prefix_unchanged:
                    offset = row["bytes_read"]
                else:
                    _remove_source_rows(conn, str(p))
            slug = _project_slug(p, root)
            sub = scan_file(p, slug, conn, start_byte=offset)
            # Persist the byte offset of the last fully-parsed line (not
            # st_size) so a partial line mid-flush is retried on the next
            # scan instead of being skipped over.
            conn.execute(
                "INSERT OR REPLACE INTO files "
                "(path, mtime, bytes_read, scanned_at, content_sig) VALUES (?, ?, ?, ?, ?)",
                (
                    str(p), stat.st_mtime, sub["end_offset"], time.time(),
                    _prefix_signature(p, sub["end_offset"]),
                ),
            )
            conn.commit()
            totals["messages"] += sub["messages"]
            totals["tools"]    += sub["tools"]
            totals["files"]    += 1
    return totals


def scan_roots(projects_roots: Iterable[Union[str, Path]], db_path: Union[str, Path]) -> dict:
    """Scan multiple Claude-compatible project roots into one dashboard DB."""
    try:
        with process_lock(f"{db_path}.scan.lock"):
            return _scan_roots_unlocked(projects_roots, db_path)
    except AlreadyRunning:
        return {"messages": 0, "tools": 0, "files": 0, "roots": 0, "locked": True}


def _scan_roots_unlocked(projects_roots, db_path) -> dict:
    totals = {"messages": 0, "tools": 0, "files": 0, "roots": 0}
    seen: set[Path] = set()
    for raw_root in projects_roots:
        root = Path(raw_root).expanduser()
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        if not root.is_dir():
            continue
        sub = scan_dir(root, db_path)
        totals["roots"] += 1
        totals["messages"] += sub["messages"]
        totals["tools"] += sub["tools"]
        totals["files"] += sub["files"]
    return totals
