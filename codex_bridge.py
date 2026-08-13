#!/usr/bin/env python3
"""Build a Divergence Ledger-compatible view of Codex session usage."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from token_dashboard.locking import process_lock


HOME = Path.home()
DEFAULT_OUTPUT = HOME / ".cache" / "divergence-ledger" / "codex-projects"
DEFAULT_ROOTS = [
    HOME / ".codex" / "sessions",
    HOME / ".codex" / "archived_sessions",
]
STATE_FILE = ".codex_bridge_state.json"
BRIDGE_FORMAT_VERSION = 6

SKILL_PATH_RE = re.compile(r"(/[A-Za-z0-9_.:@%+\-/]+/SKILL\.md)")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.MULTILINE)
CUSTOM_TOOL_RE = re.compile(r"\btools\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CUSTOM_TOOL_ALIASES = {
    "exec_command": "Bash",
    "apply_patch": "Edit",
    "view_image": "Read",
    "read_mcp_resource": "Read",
}
KNOWN_GENERIC_TOOLS = {
    "Bash", "shell_command", "search", "js", "js_reset",
    "update_plan", "write_stdin", "wait", "request_user_input", "view_image",
    "read_mcp_resource", "list_mcp_resources", "list_mcp_resource_templates",
    "send_message", "followup_task", "interrupt_agent", "list_agents", "wait_agent",
    "spawn_agent", "create_goal", "get_goal", "update_goal",
    "create_directory", "get_file_info", "evaluate_script", "new_page",
    "select_page", "close_page", "navigate_page", "load_workspace_dependencies",
}
KNOWN_TOOL_PREFIXES = (
    "browser_", "mcp__", "search_", "list_", "query_", "resolve_", "fetch_",
    "read_", "load_", "select_", "close_", "navigate_", "evaluate_", "create_",
)


def parse_args(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def skill_slug_from_path(raw_path: str) -> str | None:
    path = Path(raw_path)
    if path.name != "SKILL.md" or not path.parent.name:
        return None
    skill = path.parent.name
    parts = path.parts

    try:
        skills_idx = len(parts) - 1 - parts[::-1].index("skills")
    except ValueError:
        skills_idx = -1

    if "plugins" in parts and "cache" in parts and skills_idx > 1:
        prev = parts[skills_idx - 1]
        plugin = parts[skills_idx - 2] if re.fullmatch(r"[0-9a-f]{7,}", prev) and skills_idx > 2 else prev
        if plugin and plugin not in {"cache", "plugins", "marketplaces", ".", ".."}:
            return f"{plugin}:{skill}"

    if ".system" in parts and len(parts) >= 4:
        parent = path.parent.parent.name
        grandparent = path.parent.parent.parent.name
        if grandparent == ".system" and parent and parent not in {".", ".."}:
            return f"{parent}:{skill}"

    return skill


def extract_skill_blocks(value: object, prefix: str = "skill") -> list[dict]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    seen: set[str] = set()
    out = []
    for raw_path in sorted(set(SKILL_PATH_RE.findall(text))):
        slug = skill_slug_from_path(raw_path)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append({"type": "tool_use", "id": f"{prefix}-skill-{len(seen)}", "name": "Skill", "input": {"skill": slug}})
    return out


def block(tool_id: str | None, name: str, input_data: dict) -> dict:
    digest = hashlib.sha256(
        f"{name}\x1f{json.dumps(input_data, sort_keys=True, ensure_ascii=False)}".encode("utf-8", "replace")
    ).hexdigest()
    return {
        "type": "tool_use",
        "id": tool_id or f"codex-tool-{digest}",
        "name": name,
        "input": input_data,
    }


def patch_paths(patch_text: str) -> list[str]:
    return [m.strip() for m in PATCH_FILE_RE.findall(patch_text or "") if m.strip()]


def normalize_tool_call(name: str, args: dict, call_id: str | None) -> list[dict]:
    short_name = name.rsplit(".", 1)[-1]
    out: list[dict] = []

    if short_name in {"parallel"} and isinstance(args.get("tool_uses"), list):
        for i, nested in enumerate(args["tool_uses"]):
            if not isinstance(nested, dict):
                continue
            nested_name = str(nested.get("recipient_name") or nested.get("name") or "")
            nested_args = nested.get("parameters") if isinstance(nested.get("parameters"), dict) else {}
            out.extend(normalize_tool_call(nested_name, nested_args, f"{call_id or 'parallel'}-{i}"))
        return out

    if short_name in {"exec_command", "shell_command"}:
        cmd = args.get("cmd") or args.get("command")
        if isinstance(cmd, str) and cmd:
            out.append(block(call_id, "Bash", {"command": cmd[:500]}))
    elif short_name in {"read_text_file", "read_file", "read_media_file"}:
        path = args.get("path")
        if isinstance(path, str):
            out.append(block(call_id, "Read", {"file_path": path[:500]}))
    elif short_name == "read_multiple_files":
        for i, path in enumerate(args.get("paths") or []):
            if isinstance(path, str):
                out.append(block(f"{call_id or 'read-many'}-{i}", "Read", {"file_path": path[:500]}))
    elif short_name in {"edit_file", "move_file"}:
        path = args.get("path") or args.get("source")
        if isinstance(path, str):
            out.append(block(call_id, "Edit", {"file_path": path[:500]}))
    elif short_name == "write_file":
        path = args.get("path")
        if isinstance(path, str):
            out.append(block(call_id, "Write", {"file_path": path[:500]}))
    elif short_name == "apply_patch":
        patch_text = args.get("cmd") or args.get("patch") or ""
        for i, path in enumerate(patch_paths(patch_text if isinstance(patch_text, str) else "")):
            out.append(block(f"{call_id or 'patch'}-{i}", "Edit", {"file_path": path[:500]}))
    elif short_name in {"search_files"}:
        pattern = args.get("pattern")
        if isinstance(pattern, str):
            out.append(block(call_id, "Glob", {"pattern": pattern[:500]}))
    elif short_name in {"get_file_contents"}:
        target = args.get("path")
        if isinstance(target, str):
            owner = args.get("owner") or ""
            repo = args.get("repo") or ""
            out.append(block(call_id, "Read", {"file_path": f"github:{owner}/{repo}/{target}"[:500]}))
    elif short_name in {"browser_navigate", "open"}:
        url = args.get("url") or args.get("ref_id")
        if isinstance(url, str):
            out.append(block(call_id, "WebFetch", {"url": url[:500]}))
    elif short_name in {"search_query", "image_query"}:
        query = args.get("q")
        if isinstance(query, str):
            out.append(block(call_id, "WebSearch", {"query": query[:500]}))

    if not out:
        item = block(call_id, CUSTOM_TOOL_ALIASES.get(short_name, short_name or "unknown"), {})
        normalized_name = str(item.get("name") or short_name)
        if (short_name not in KNOWN_GENERIC_TOOLS
                and normalized_name not in KNOWN_GENERIC_TOOLS
                and not short_name.startswith(KNOWN_TOOL_PREFIXES)):
            item["quality_warning"] = "unknown_tool_type"
        out.append(item)
    out.extend(extract_skill_blocks(args, call_id or short_name or "skill"))
    return out


def custom_tool_names(source: str) -> list[str]:
    """Find tools.foo(...) calls in wrapper JS, excluding strings and comments."""
    names: list[str] = []
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            newline = source.find("\n", i + 2)
            i = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = len(source) if end < 0 else end + 2
            continue
        if source[i] in "'\"`":
            quote = source[i]
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        match = CUSTOM_TOOL_RE.match(source, i)
        if match:
            names.append(match.group(1))
            i = match.end()
            continue
        i += 1
    return names


def normalize_custom_tool_call(name: str, raw_input: object, call_id: str | None) -> list[dict]:
    short_name = name.rsplit(".", 1)[-1]
    if short_name != "exec":
        args = parse_args(raw_input)
        if short_name == "apply_patch" and not args and isinstance(raw_input, str):
            args = {"patch": raw_input}
        return normalize_tool_call(short_name, args, call_id)
    if not isinstance(raw_input, str):
        return []
    out = [
        block(
            f"{call_id or 'custom'}-{index}",
            CUSTOM_TOOL_ALIASES.get(name, name),
            {},
        )
        for index, name in enumerate(custom_tool_names(raw_input))
    ]
    out.extend(extract_skill_blocks(raw_input, call_id or "custom"))
    return out


def project_slug(cwd: str | None) -> str:
    if not cwd:
        return "codex"
    slug = re.sub(r"[:\\/ ]", "-", cwd.rstrip("/\\"))
    return slug or "codex"


def safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stable_key(*parts: object) -> str:
    raw = "\x1f".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _chars(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_chars(k) + _chars(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(_chars(item) for item in value)
    return 0


def iter_jsonl_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.name.endswith(".jsonl"):
            files.append(root)
            continue
        if root.is_dir():
            files.extend(root.rglob("*.jsonl"))
    return sorted(files, key=lambda path: (path.stat().st_mtime, str(path)))


def read_jsonl(path: Path, quality: dict | None = None):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if quality is not None:
                        quality["raw_json_events"] = quality.get("raw_json_events", 0) + 1
                    yield event
                except json.JSONDecodeError:
                    if quality is not None:
                        quality["damaged_lines"] = quality.get("damaged_lines", 0) + 1
                    continue
    except OSError:
        if quality is not None:
            quality["read_errors"] = quality.get("read_errors", 0) + 1
        return


def thread_metadata(path: Path) -> dict:
    fallback = path.stem.rsplit("-", 1)[-1] if path.stem.startswith("rollout-") else path.stem
    for event in read_jsonl(path):
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload") or {}
        session_id = payload.get("id") or payload.get("session_id") or fallback
        parent = payload.get("parent_thread_id") or payload.get("forked_from_id")
        return {
            "session_id": str(session_id),
            "parent_thread_id": str(parent) if parent else None,
            "cwd": payload.get("cwd"),
            "is_subagent": bool(parent or payload.get("agent_role") or payload.get("agent_nickname")),
        }
    return {"session_id": fallback, "parent_thread_id": None, "cwd": None, "is_subagent": False}


def convert_file(path: Path, quality: dict | None = None) -> tuple[str, str, list[dict]]:
    quality = quality if quality is not None else {}
    metadata = thread_metadata(path)
    session_id = metadata["session_id"]
    cwd = metadata["cwd"]
    model = "codex"
    records: list[dict] = []
    parent_thread_id = metadata["parent_thread_id"]
    root_session_id = parent_thread_id or session_id
    is_subagent = metadata["is_subagent"]
    depth = 1 if parent_thread_id else 0
    seen_users: set[str] = set()
    last_total = None
    epoch = 0
    last_usage_key = None
    current_user_uuid = None
    current_turn_id = None
    response_keys: list[str] = []
    pending_tools: list[dict] = []
    pending_results: list[dict] = []
    last_timestamp = None

    for event_index, event in enumerate(read_jsonl(path, quality)):
        last_timestamp = event.get("timestamp") or last_timestamp
        payload = event.get("payload") or {}
        event_type = event.get("type")

        if event_type == "response_item":
            payload_type = payload.get("type")
            if payload_type not in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
                response_key = payload.get("id") or payload.get("call_id")
                if response_key:
                    response_keys.append(str(response_key))
            if payload_type == "function_call" and payload.get("name"):
                args = parse_args(payload.get("arguments"))
                pending_tools.extend(normalize_tool_call(str(payload.get("name")), args, payload.get("call_id")))
                continue
            if payload_type == "custom_tool_call":
                pending_tools.extend(
                    normalize_custom_tool_call(
                        str(payload.get("name") or ""), payload.get("input"), payload.get("call_id")
                    )
                )
                continue
            if payload_type in {"function_call_output", "custom_tool_call_output"}:
                output = payload.get("output")
                chars = _chars(output)
                pending_results.append({
                    "type": "tool_result",
                    "tool_use_id": payload.get("call_id"),
                    "content": "",
                    "result_tokens": chars // 4,
                    "result_estimated": True,
                    "is_error": False,
                })
                continue

        if event_type == "session_meta":
            cwd = payload.get("cwd") or cwd
            continue

        if event_type == "turn_context":
            model = payload.get("model") or model
            current_turn_id = payload.get("turn_id") or current_turn_id
            continue

        if event_type == "event_msg" and payload.get("type") == "task_started":
            current_turn_id = payload.get("turn_id") or current_turn_id
            continue

        if event_type == "event_msg" and payload.get("type") == "user_message":
            client_id = payload.get("client_id") or payload.get("id")
            if client_id and client_id in seen_users:
                continue
            user_key = str(client_id or _stable_key(
                event.get("timestamp") or payload.get("timestamp"),
                payload.get("message") or payload.get("content"),
            ))
            seen_users.add(user_key)
            user_uuid = f"codex-user-{_stable_key(session_id, user_key)}"
            current_user_uuid = user_uuid
            timestamp = event.get("timestamp") or payload.get("timestamp")
            records.append({
                "uuid": user_uuid,
                "parentUuid": None,
                "sessionId": session_id,
                "rootSessionId": root_session_id or session_id,
                "parentSessionId": parent_thread_id,
                "isSubagent": is_subagent,
                "threadDepth": depth,
                "eventKey": f"user:{user_key}",
                "cwd": cwd,
                "version": "codex-bridge",
                "type": "user",
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "id": user_key,
                    "client_id": user_key,
                    "content": "[prompt omitted by divergence-ledger]",
                    "prompt_chars": _chars(payload.get("message") or payload.get("content")),
                },
            })
            continue

        info = payload.get("info") or {}
        usage = info.get("last_token_usage")
        if not isinstance(usage, dict):
            continue
        quality["raw_usage_events"] = quality.get("raw_usage_events", 0) + 1

        input_total = safe_int(usage.get("input_tokens"))
        cache_read = safe_int(usage.get("cached_input_tokens"))
        output_tokens = safe_int(usage.get("output_tokens"))
        cache_write = safe_int(usage.get("cache_write_input_tokens"))
        reasoning = safe_int(usage.get("reasoning_output_tokens"))
        total = info.get("total_token_usage")
        total_vec = tuple(safe_int(total.get(k)) for k in (
            "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens", "total_tokens",
        )) if isinstance(total, dict) else None
        if total_vec is not None:
            if last_total is not None and total_vec == last_total:
                quality["duplicate_usage_events"] = quality.get("duplicate_usage_events", 0) + 1
                response_keys = []
                continue
            if last_total is not None and any(a < b for a, b in zip(total_vec, last_total)):
                epoch += 1
            last_total = total_vec
            response_id = _stable_key(*sorted(set(response_keys))) if response_keys else None
            stable_id = response_id or (str(current_turn_id) if current_turn_id else None)
            usage_key = (
                f"usage:{stable_id}:{epoch}:{total_vec}"
                if stable_id else f"usage:{epoch}:{total_vec}"
            )
        else:
            response_id = _stable_key(*sorted(set(response_keys))) if response_keys else None
            stable_id = response_id or (str(current_turn_id) if current_turn_id else None)
            usage_key = f"usage-event:{stable_id or event.get('timestamp') or event_index}"
        response_keys = []
        if usage_key == last_usage_key:
            quality["duplicate_usage_events"] = quality.get("duplicate_usage_events", 0) + 1
            continue
        last_usage_key = usage_key

        if input_total == 0 and cache_read == 0 and cache_write == 0 and output_tokens == 0:
            quality["zero_usage_snapshots"] = quality.get("zero_usage_snapshots", 0) + 1
            continue

        flags = []
        bounded_cache_read = min(max(cache_read, 0), max(input_total, 0))
        bounded_cache_write = min(max(cache_write, 0), max(input_total - bounded_cache_read, 0))
        if bounded_cache_read != cache_read or bounded_cache_write != cache_write:
            flags.append("input_bucket_corrected")
            quality["bucket_corrections"] = quality.get("bucket_corrections", 0) + 1
        cache_read = bounded_cache_read
        cache_write = bounded_cache_write
        ordinary_input = max(input_total - cache_read - cache_write, 0)
        if "cache_write_input_tokens" not in usage:
            cache_write = ordinary_input
            ordinary_input = 0
        timestamp = event.get("timestamp") or payload.get("timestamp")
        assistant_uuid = f"codex-assistant-{_stable_key(session_id, usage_key)}"
        records.append(
            {
                "uuid": assistant_uuid,
                "parentUuid": current_user_uuid,
                "sessionId": session_id,
                "rootSessionId": root_session_id or session_id,
                "parentSessionId": parent_thread_id,
                "isSubagent": is_subagent,
                "threadDepth": depth,
                "eventKey": usage_key,
                "qualityFlags": flags,
                "cwd": cwd,
                "version": "codex-bridge",
                "type": "assistant",
                "timestamp": timestamp,
                "message": {
                    "id": assistant_uuid,
                    "role": "assistant",
                    "model": model,
                    "content": [*pending_tools, *pending_results],
                    "usage": {
                        "id": assistant_uuid,
                        "original_input_tokens": input_total,
                        "input_tokens": ordinary_input,
                        "output_tokens": output_tokens,
                        "reasoning_output_tokens": reasoning,
                        "cache_read_input_tokens": cache_read,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": cache_write,
                            "ephemeral_1h_input_tokens": 0,
                        },
                    },
                },
            }
        )
        for position, item in enumerate(pending_tools):
            item.setdefault("event_key", f"tool:{item.get('id') or _stable_key(assistant_uuid, item.get('name'))}")
            if not item.get("id"):
                item["event_key"] += f":{position}"
        for position, item in enumerate(pending_results):
            item.setdefault("event_key", f"result:{item.get('tool_use_id') or _stable_key(assistant_uuid, item.get('result_tokens'), position)}")
        pending_tools = []
        pending_results = []

    # A tool call can be the final event in an aborted session. Attach it to a
    # lightweight assistant row so scanner ingestion never drops EOF data.
    if pending_tools or pending_results:
        timestamp = last_timestamp or (records[-1].get("timestamp") if records else None)
        eof_key = _stable_key(
            *(item.get("id") or item.get("tool_use_id") or item.get("event_key") for item in [*pending_tools, *pending_results])
        )
        assistant_uuid = f"codex-tools-{_stable_key(session_id, eof_key)}"
        records.append({
            "uuid": assistant_uuid, "parentUuid": current_user_uuid, "sessionId": session_id,
            "rootSessionId": root_session_id or session_id, "parentSessionId": parent_thread_id,
            "isSubagent": is_subagent, "threadDepth": depth, "eventKey": f"eof:{eof_key}",
            "cwd": cwd, "version": "codex-bridge", "type": "assistant", "timestamp": timestamp,
            "message": {"id": assistant_uuid, "role": "assistant", "model": model,
                        "content": [*pending_tools, *pending_results], "usage": {}},
        })

    return session_id, project_slug(cwd), records


def write_records(output_root: Path, session_id: str, slug: str, records: list[dict]) -> Path | None:
    if not records:
        return None
    target_dir = output_root / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{session_id}.jsonl"
    tmp = target.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    tmp.replace(target)
    return target


def load_state(output_root: Path) -> dict:
    path = output_root / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": BRIDGE_FORMAT_VERSION, "sources": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        return {"version": BRIDGE_FORMAT_VERSION, "sources": {}}
    return data


def write_state(output_root: Path, state: dict) -> None:
    path = output_root / STATE_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def source_state_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def relative_output_path(output_root: Path, target: Path | None) -> str | None:
    if target is None:
        return None
    try:
        return str(target.relative_to(output_root))
    except ValueError:
        return str(target)


def unchanged_source(prior: dict | None, stat) -> bool:
    if not isinstance(prior, dict):
        return False
    return prior.get("mtime") == stat.st_mtime and prior.get("size") == stat.st_size


def _family_root(session_id: str, parents: dict[str, str | None]) -> tuple[str, int]:
    current = session_id
    seen = {current}
    depth = 0
    while parents.get(current) and parents[current] not in seen:
        current = str(parents[current])
        seen.add(current)
        depth += 1
    return current, depth


def _dedupe_family(records: list[dict], root_session_id: str, depths: dict[str, int]) -> tuple[list[dict], int]:
    chosen: dict[tuple[str, str], dict] = {}
    duplicates = 0
    for record in records:
        session_id = record.get("sessionId") or root_session_id
        record["rootSessionId"] = root_session_id
        record["threadDepth"] = depths.get(session_id, record.get("threadDepth") or 0)
        key = (str(record.get("type") or ""), str(record.get("eventKey") or record.get("uuid") or ""))
        prior = chosen.get(key)
        if prior is None:
            chosen[key] = record
            continue
        duplicates += 1
        if record.get("isSubagent") and not prior.get("isSubagent"):
            chosen[key] = record
    kept = list(chosen.values())
    users_by_event = {
        record.get("eventKey"): record.get("uuid")
        for record in kept if record.get("type") == "user"
    }
    replaced_user_uuids = {
        record.get("uuid"): users_by_event.get(record.get("eventKey"))
        for record in records if record.get("type") == "user"
        if users_by_event.get(record.get("eventKey"))
    }
    for record in kept:
        if record.get("parentUuid") in replaced_user_uuids:
            record["parentUuid"] = replaced_user_uuids[record["parentUuid"]]
    return sorted(kept, key=lambda r: (r.get("timestamp") or "", r.get("uuid") or "")), duplicates


def sync_once(output_root: Path, roots: list[Path]) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    prior_state = load_state(output_root)
    prior_sources = (
        prior_state.get("sources") or {}
        if prior_state.get("version") == BRIDGE_FORMAT_VERSION
        else {}
    )
    next_sources: dict[str, dict] = {}
    family_quality: dict[str, dict] = {}
    written: set[Path] = set()
    sessions = records = skipped = duplicates = raw_events = 0
    quality = {
        "raw_json_events": 0,
        "raw_usage_events": 0, "duplicate_usage_events": 0,
        "zero_usage_snapshots": 0, "damaged_lines": 0, "read_errors": 0,
        "bucket_corrections": 0, "unknown_tool_types": 0,
    }
    sources = iter_jsonl_files(roots)
    metadata = {source: thread_metadata(source) for source in sources}
    parents = {item["session_id"]: item["parent_thread_id"] for item in metadata.values()}
    families: dict[str, list[Path]] = {}
    depths: dict[str, int] = {}
    for source, item in metadata.items():
        root, depth = _family_root(item["session_id"], parents)
        depths[item["session_id"]] = depth
        families.setdefault(root, []).append(source)

    for family_id, family_sources in families.items():
        source_rows = []
        for source in family_sources:
            try:
                stat = source.stat()
            except OSError:
                continue
            key = source_state_key(source)
            source_rows.append((source, stat, key, prior_sources.get(key)))
        if not source_rows:
            continue

        raw_target = next((row[3].get("target") for row in source_rows if isinstance(row[3], dict) and row[3].get("target")), None)
        if raw_target and all(unchanged_source(row[3], row[1]) for row in source_rows):
            target = output_root / raw_target
            if target.is_file():
                written.add(target.resolve())
                for _, _, key, prior in source_rows:
                    next_sources[key] = prior
                representative = source_rows[0][3] or {}
                sessions += 1
                records += safe_int(representative.get("family_records"))
                raw_events += safe_int(representative.get("family_raw_events"))
                duplicates += safe_int(representative.get("family_duplicates"))
                prior_family_quality = (prior_state.get("family_quality") or {}).get(family_id)
                if isinstance(prior_family_quality, dict):
                    family_quality[family_id] = prior_family_quality
                skipped += len(source_rows)
                continue

        converted_records = []
        local_quality = {
            "raw_json_events": 0, "raw_usage_events": 0, "duplicate_usage_events": 0,
            "zero_usage_snapshots": 0, "damaged_lines": 0, "read_errors": 0,
            "bucket_corrections": 0, "unknown_tool_types": 0,
        }
        slug = "codex"
        for source, _, _, _ in source_rows:
            _, source_slug, converted = convert_file(source, local_quality)
            if slug == "codex":
                slug = source_slug
            converted_records.extend(converted)
        merged, family_duplicates = _dedupe_family(converted_records, family_id, depths)
        local_quality["unknown_tool_types"] += sum(
            1 for record in merged
            for item in ((record.get("message") or {}).get("content") or [])
            if isinstance(item, dict) and item.get("quality_warning") == "unknown_tool_type"
        )
        target = write_records(output_root, family_id, slug, merged)
        target_rel = relative_output_path(output_root, target)
        for index, (_, stat, key, _) in enumerate(source_rows):
            next_sources[key] = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "target": target_rel,
                "family_id": family_id,
                "family_records": len(merged) if index == 0 else 0,
                "family_raw_events": len(converted_records) if index == 0 else 0,
                "family_duplicates": family_duplicates if index == 0 else 0,
            }
        raw_events += len(converted_records)
        duplicates += family_duplicates
        if target is not None:
            written.add(target.resolve())
            sessions += 1
            records += len(merged)
        family_quality[family_id] = local_quality

    for existing in output_root.rglob("*.jsonl"):
        if existing.resolve() not in written:
            existing.unlink(missing_ok=True)

    for item in family_quality.values():
        for key in quality:
            quality[key] += safe_int(item.get(key))
    write_state(output_root, {
        "version": BRIDGE_FORMAT_VERSION,
        "sources": next_sources,
        "family_quality": family_quality,
        "quality": {
            "source_files": len(sources),
            "thread_families": len(families),
            "raw_events": raw_events,
            "accepted_events": records,
            "duplicate_events": duplicates,
            **quality,
        },
    })

    return {"sessions": sessions, "records": records, "skipped": skipped,
            "duplicates": duplicates, "output": str(output_root)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Codex token usage into Divergence Ledger input format")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Bridge output directory")
    parser.add_argument("--root", action="append", dest="roots", help="Codex JSONL root; may be repeated")
    parser.add_argument("--watch", action="store_true", help="Keep syncing")
    parser.add_argument("--interval", type=float, default=30.0, help="Watch interval in seconds")
    args = parser.parse_args()

    roots = [Path(root).expanduser() for root in args.roots] if args.roots else DEFAULT_ROOTS
    output = Path(args.output).expanduser()

    output.mkdir(parents=True, exist_ok=True)
    with process_lock(output / ".bridge.lock"):
        while True:
            summary = sync_once(output, roots)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if not args.watch:
                return
            time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    main()
