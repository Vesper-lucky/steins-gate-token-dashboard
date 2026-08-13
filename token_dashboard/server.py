"""HTTP server: static frontend + JSON endpoints + SSE diff stream."""
from __future__ import annotations

import http.server
import json
import mimetypes
import os
import queue
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .db import (
    overview_totals, expensive_prompts, project_summary,
    tool_token_breakdown, recent_sessions, session_turns,
    daily_model_token_breakdown, daily_token_breakdown,
    model_breakdown, skill_breakdown,
    project_model_breakdown,
    today_hourly_model_token_breakdown, today_hourly_token_breakdown,
    token_duo_total_tokens,
    data_quality,
)
from .pricing import load_pricing, cost_for, get_plan, pricing_cutoffs, set_plan
from .tips import all_tips, dismiss_tip
from .scanner import scan_roots
from .skills import cached_catalog
from .locking import process_lock


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
PRICING_JSON = Path(__file__).resolve().parent.parent / "pricing.json"

EVENTS: "queue.Queue[dict]" = queue.Queue()
SCAN_LOCK = threading.Lock()

MAX_POST_BYTES = 1_000_000  # 1 MB — we only accept tiny JSON bodies (plan, tip key)
MAX_LIMIT = 1000


def _period_usage_tokens(row: dict) -> int:
    return (
        (row.get("input_tokens") or 0)
        + (row.get("cache_create_tokens") or 0)
        + (row.get("cache_read_tokens") or 0)
        + (row.get("output_tokens") or 0)
    )


def _model_period_detail(row: dict, pricing: dict) -> dict:
    cache_create_tokens = (
        (row.get("cache_create_5m_tokens") or 0)
        + (row.get("cache_create_1h_tokens") or 0)
    )
    total_tokens = (
        (row.get("input_tokens") or 0)
        + (row.get("output_tokens") or 0)
        + (row.get("cache_read_tokens") or 0)
        + cache_create_tokens
    )
    c = cost_for(row["model"], row, pricing, at=row.get("pricing_at"))
    return {
        "model": row["model"],
        "input_tokens": row.get("input_tokens") or 0,
        "output_tokens": row.get("output_tokens") or 0,
        "cache_read_tokens": row.get("cache_read_tokens") or 0,
        "cache_create_tokens": cache_create_tokens,
        "total_tokens": total_tokens,
        "cost_usd": c["usd"],
    }


def _annotate_period_costs(rows: list, model_rows: list, period_key: str, pricing: dict) -> list:
    costs = {}
    model_details = {}
    for r in model_rows:
        c = cost_for(r["model"], r, pricing, at=r.get("pricing_at"))
        period = r[period_key]
        detail = _model_period_detail(r, pricing)
        by_model = model_details.setdefault(period, {})
        merged = by_model.setdefault(r["model"], {
            "model": r["model"],
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_create_tokens": 0,
            "total_tokens": 0,
            "cost_usd": None,
        })
        for key in (
            "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_create_tokens", "total_tokens",
        ):
            merged[key] += detail[key]
        if detail["cost_usd"] is not None:
            merged["cost_usd"] = (merged["cost_usd"] or 0.0) + detail["cost_usd"]
        breakdown = c.get("breakdown") or {}
        if not breakdown:
            continue
        agg = costs.setdefault(period, {
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_create_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
        })
        agg["input_cost_usd"] += breakdown.get("input", 0.0)
        agg["output_cost_usd"] += breakdown.get("output", 0.0)
        agg["cache_create_cost_usd"] += (
            breakdown.get("cache_create_5m", 0.0)
            + breakdown.get("cache_create_1h", 0.0)
        )
        agg["cache_read_cost_usd"] += breakdown.get("cache_read", 0.0)

    for row in rows:
        period = row[period_key]
        period_costs = costs.get(period, {})
        row["models"] = sorted(
            model_details.get(period, {}).values(),
            key=lambda item: (-(item["total_tokens"] or 0), item["model"]),
        )
        for detail in row["models"]:
            if detail["cost_usd"] is not None:
                detail["cost_usd"] = round(detail["cost_usd"], 6)
        row["usage_tokens"] = _period_usage_tokens(row)
        row["input_cost_usd"] = round(period_costs.get("input_cost_usd", 0.0), 6)
        row["output_cost_usd"] = round(period_costs.get("output_cost_usd", 0.0), 6)
        row["cache_create_cost_usd"] = round(period_costs.get("cache_create_cost_usd", 0.0), 6)
        row["cache_read_cost_usd"] = round(period_costs.get("cache_read_cost_usd", 0.0), 6)
        row["usage_cost_usd"] = round(
            row["input_cost_usd"]
            + row["output_cost_usd"]
            + row["cache_create_cost_usd"]
            + row["cache_read_cost_usd"],
            6,
        )
    return rows


def _annotate_project_costs(rows: list, model_rows: list, pricing: dict) -> list:
    costs = {}
    for r in model_rows:
        c = cost_for(r["model"], r, pricing, at=r.get("pricing_at"))
        if c["usd"] is None:
            continue
        costs[r["project_slug"]] = costs.get(r["project_slug"], 0.0) + c["usd"]
    for row in rows:
        row["cost_usd"] = round(costs.get(row["project_slug"], 0.0), 6)
    return rows


def _annotate_model_costs(rows: list, pricing: dict) -> list:
    token_keys = (
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_create_5m_tokens", "cache_create_1h_tokens",
        "reasoning_output_tokens",
        "long_context_input_tokens", "long_context_output_tokens",
        "long_context_cache_read_tokens", "long_context_cache_create_5m_tokens",
        "long_context_cache_create_1h_tokens",
    )
    merged = {}
    for row in rows:
        model = row["model"]
        item = merged.setdefault(model, {
            "model": model,
            "turns": 0,
            **{key: 0 for key in token_keys},
            "cost_usd": None,
            "cost_estimated": False,
        })
        item["turns"] += row.get("turns") or 0
        for key in token_keys:
            item[key] += row.get(key) or 0
        c = cost_for(model, row, pricing, at=row.get("pricing_at"))
        item["cost_estimated"] = item["cost_estimated"] or c["estimated"]
        if c["usd"] is not None:
            item["cost_usd"] = (item["cost_usd"] or 0.0) + c["usd"]

    result = list(merged.values())
    for item in result:
        if item["cost_usd"] is not None:
            item["cost_usd"] = round(item["cost_usd"], 6)
    result.sort(key=lambda item: -(
        item["input_tokens"] + item["output_tokens"]
        + item["cache_read_tokens"]
        + item["cache_create_5m_tokens"] + item["cache_create_1h_tokens"]
    ))
    return result


def _send_json(handler, obj, status: int = 200) -> None:
    body = json.dumps(obj, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_error(handler, status: int, msg: str) -> None:
    _send_json(handler, {"error": msg}, status=status)


def _clamp_limit(raw, default: int) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(v, MAX_LIMIT))


def _serve_static(handler, rel: str) -> None:
    rel = rel.lstrip("/")
    p = (WEB_ROOT / rel).resolve()
    if not str(p).startswith(str(WEB_ROOT.resolve())) or not p.is_file():
        handler.send_response(404)
        handler.end_headers()
        return
    body = p.read_bytes()
    ctype, _ = mimetypes.guess_type(str(p))
    handler.send_response(200)
    handler.send_header("Content-Type", ctype or "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _project_roots(projects_dirs) -> list[str]:
    if isinstance(projects_dirs, (str, os.PathLike)):
        return [str(projects_dirs)]
    return [str(path) for path in projects_dirs]


def _scan_once(projects_dirs, db_path: str, block: bool = True):
    if not SCAN_LOCK.acquire(blocking=block):
        return None
    try:
        return scan_roots(_project_roots(projects_dirs), db_path)
    finally:
        SCAN_LOCK.release()


def build_handler(db_path: str, projects_dir):
    pricing = load_pricing(PRICING_JSON)
    cutoffs = pricing_cutoffs(pricing)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_HEAD(self):
            return self.do_GET()

        def do_GET(self):
            url = urlparse(self.path)
            qs = parse_qs(url.query or "")
            path = url.path
            since = qs.get("since", [None])[0]
            until = qs.get("until", [None])[0]
            if path == "/api/health":
                return _send_json(self, {"ok": True, "product": "Divergence Ledger"})
            if path in ("/", "/index.html"):
                return _serve_static(self, "index.html")
            if path.startswith("/web/"):
                return _serve_static(self, path[5:])
            if path == "/api/overview":
                with SCAN_LOCK:
                    totals = overview_totals(db_path, since, until)
                    models = model_breakdown(db_path, since, until, cutoffs)
                cost_usd = 0.0
                for m in models:
                    c = cost_for(m["model"], m, pricing, at=m.get("pricing_at"))
                    if c["usd"] is not None:
                        cost_usd += c["usd"]
                totals["cost_usd"] = round(cost_usd, 4)
                return _send_json(self, totals)
            if path == "/api/token-duo":
                scan = None
                refresh = (qs.get("refresh", ["0"])[0] or "").lower()
                if refresh in {"1", "true", "yes"}:
                    scan = _scan_once(projects_dir, db_path, block=False)
                return _send_json(self, {
                    "total_tokens": token_duo_total_tokens(db_path, since, until),
                    "refreshed": scan is not None,
                    "scan": scan,
                })
            if path == "/api/prompts":
                limit = _clamp_limit(qs.get("limit", ["50"])[0], 50)
                sort = qs.get("sort", ["tokens"])[0]
                rows = expensive_prompts(db_path, limit=limit, sort=sort)
                for r in rows:
                    costs = [
                        cost_for(segment["model"], segment, pricing, at=segment.get("pricing_at"))["usd"]
                        for segment in r.pop("pricing_segments", [])
                    ]
                    r["estimated_cost_usd"] = (
                        round(sum(cost for cost in costs if cost is not None), 6)
                        if any(cost is not None for cost in costs) else None
                    )
                return _send_json(self, rows)
            if path == "/api/projects":
                with SCAN_LOCK:
                    rows = project_summary(db_path, since, until)
                    model_rows = project_model_breakdown(db_path, since, until, cutoffs)
                return _send_json(self, _annotate_project_costs(rows, model_rows, pricing))
            if path == "/api/tools":
                return _send_json(self, tool_token_breakdown(db_path, since, until))
            if path == "/api/sessions":
                return _send_json(self, recent_sessions(
                    db_path, limit=_clamp_limit(qs.get("limit", ["20"])[0], 20),
                    since=since, until=until,
                ))
            if path == "/api/daily":
                with SCAN_LOCK:
                    rows = daily_token_breakdown(db_path, since, until)
                    model_rows = daily_model_token_breakdown(db_path, since, until, cutoffs)
                return _send_json(self, _annotate_period_costs(rows, model_rows, "day", pricing))
            if path == "/api/today-hourly":
                with SCAN_LOCK:
                    rows = today_hourly_token_breakdown(db_path)
                    model_rows = today_hourly_model_token_breakdown(db_path, pricing_cutoffs=cutoffs)
                return _send_json(self, _annotate_period_costs(rows, model_rows, "hour_index", pricing))
            if path == "/api/skills":
                rows = skill_breakdown(db_path, since, until)
                catalog = cached_catalog()
                for r in rows:
                    info = catalog.get(r["skill"])
                    r["tokens_per_call"] = info["tokens"] if info else None
                    r["tokens_per_call_estimated"] = info is not None
                return _send_json(self, rows)
            if path == "/api/by-model":
                rows = model_breakdown(db_path, since, until, cutoffs)
                return _send_json(self, _annotate_model_costs(rows, pricing))
            if path.startswith("/api/sessions/"):
                sid = path.rsplit("/", 1)[1]
                return _send_json(self, session_turns(db_path, sid))
            if path == "/api/tips":
                return _send_json(self, all_tips(db_path))
            if path == "/api/plan":
                return _send_json(self, {"plan": get_plan(db_path), "pricing": pricing})
            if path == "/api/data-quality":
                return _send_json(self, data_quality(db_path, _project_roots(projects_dir)))
            if path == "/api/scan":
                n = _scan_once(projects_dir, db_path, block=True)
                return _send_json(self, n)
            if path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                while True:
                    try:
                        evt = EVENTS.get(timeout=15)
                        chunk = f"data: {json.dumps(evt, default=str)}\n\n".encode()
                    except queue.Empty:
                        chunk = b": ping\n\n"
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            url = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return _send_error(self, 400, "invalid Content-Length")
            if length < 0 or length > MAX_POST_BYTES:
                return _send_error(self, 413, f"body too large (max {MAX_POST_BYTES} bytes)")
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except json.JSONDecodeError:
                return _send_error(self, 400, "invalid JSON")
            if not isinstance(body, dict):
                return _send_error(self, 400, "body must be a JSON object")
            if url.path == "/api/plan":
                set_plan(db_path, body.get("plan", "api"))
                return _send_json(self, {"ok": True})
            if url.path == "/api/tips/dismiss":
                dismiss_tip(db_path, body.get("key", ""))
                return _send_json(self, {"ok": True})
            self.send_response(404)
            self.end_headers()

    return H


def _scan_loop(db_path: str, projects_dir, interval: float = 30.0):
    while True:
        try:
            n = _scan_once(projects_dir, db_path, block=False)
            if n and n["messages"] > 0:
                EVENTS.put({"type": "scan", "n": n, "ts": time.time()})
        except Exception as e:
            EVENTS.put({"type": "error", "message": str(e)})
        time.sleep(interval)


def _scan_interval() -> float:
    try:
        return max(1.0, float(os.environ.get("TOKDASH_SCAN_INTERVAL", "1")))
    except ValueError:
        return 1.0


def run(host: str, port: int, db_path: str, projects_dir, scan_enabled: bool = True):
    lock_path = Path.home() / ".cache" / "divergence-ledger" / f"dashboard-{host}-{port}.lock"
    with process_lock(lock_path):
        if scan_enabled:
            threading.Thread(target=_scan_loop, args=(db_path, projects_dir, _scan_interval()), daemon=True).start()
        H = build_handler(db_path, projects_dir)
        httpd = http.server.ThreadingHTTPServer((host, port), H)
        httpd.serve_forever()
