"""Divergence Ledger CLI entrypoint."""
from __future__ import annotations

import argparse
import os
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from token_dashboard.db import BEIJING_TZ, data_quality, init_db, default_db_path, overview_totals
from token_dashboard.scanner import scan_roots
from token_dashboard.tips import all_tips


def _db_path(args) -> str:
    return args.db or os.environ.get("TOKEN_DASHBOARD_DB") or str(default_db_path())


def _split_project_roots(raw: str) -> list[str]:
    roots = [part for part in raw.split(os.pathsep) if part]
    return roots or [raw]


def _project_roots(args) -> list[str]:
    if args.projects_dir:
        return _split_project_roots(args.projects_dir)
    if os.environ.get("TOKDASH_PROJECTS_DIRS"):
        return _split_project_roots(os.environ["TOKDASH_PROJECTS_DIRS"])
    if os.environ.get("CLAUDE_PROJECTS_DIR"):
        return _split_project_roots(os.environ["CLAUDE_PROJECTS_DIR"])
    return [str(Path.home() / ".claude" / "projects")]


def _today_range(now=None):
    local_now = (now or datetime.now(BEIJING_TZ)).astimezone(BEIJING_TZ)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def cmd_scan(args):
    db = _db_path(args)
    init_db(db)
    n = scan_roots(_project_roots(args), db)
    print(f"Divergence Ledger: scanned {n['files']} files, {n['messages']} messages, {n['tools']} tool calls")


def cmd_today(args):
    db = _db_path(args)
    init_db(db)
    s, e = _today_range()
    t = overview_totals(db, since=s, until=e)
    print("Divergence Ledger - today")
    print(f"  sessions: {t['sessions']}    prompts: {t['turns']}    model calls: {t['model_calls']}")
    print(f"  input:    {t['input_tokens']:>12,}    output: {t['output_tokens']:>12,}")
    print(f"  cache rd: {t['cache_read_tokens']:>12,}    cache cr: {t['cache_create_5m_tokens']+t['cache_create_1h_tokens']:>12,}")


def cmd_stats(args):
    db = _db_path(args)
    init_db(db)
    t = overview_totals(db)
    print("Divergence Ledger - all time")
    print(f"  sessions: {t['sessions']}    prompts: {t['turns']}    model calls: {t['model_calls']}")
    print(f"  input:    {t['input_tokens']:>12,}    output: {t['output_tokens']:>12,}")


def cmd_tips(args):
    db = _db_path(args)
    init_db(db)
    tips = all_tips(db)
    if not tips:
        print("Divergence Ledger: no suggestions")
        return
    for tip in tips:
        print(f"[{tip['category']}] {tip['title']}")
        print(f"  {tip['body']}\n")


def cmd_dashboard(args):
    db = _db_path(args)
    init_db(db)
    from token_dashboard.server import run

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8081"))
    url = f"http://{host}:{port}/"
    if not args.no_open:
        webbrowser.open(url)
    print(f"Divergence Ledger listening on {url}")
    run(host, port, db, _project_roots(args), scan_enabled=not args.no_scan)


def cmd_audit(args):
    db = _db_path(args)
    init_db(db)
    report = data_quality(db, _project_roots(args))
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(2)


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="SQLite path (default ~/.claude/token-dashboard.db)")
    common.add_argument("--projects-dir", help="JSONL root (default ~/.claude/projects)")

    p = argparse.ArgumentParser(prog="divledger", description="Divergence Ledger - 世界线 Token 记录仪", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan",  parents=[common]).set_defaults(func=cmd_scan)
    sub.add_parser("today", parents=[common]).set_defaults(func=cmd_today)
    sub.add_parser("stats", parents=[common]).set_defaults(func=cmd_stats)
    sub.add_parser("tips",  parents=[common]).set_defaults(func=cmd_tips)
    sub.add_parser("audit", parents=[common]).set_defaults(func=cmd_audit)
    d = sub.add_parser("dashboard", parents=[common])
    d.add_argument("--no-scan", action="store_true")
    d.add_argument("--no-open", action="store_true")
    d.set_defaults(func=cmd_dashboard)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
