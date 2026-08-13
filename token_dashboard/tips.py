"""Rule-based tips engine — produces actionable Codex/Claude suggestions from SQLite."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .db import connect
from .pricing import cost_for, load_pricing
from .skills import tokens_for


PRICING_JSON = Path(__file__).resolve().parent.parent / "pricing.json"


def _iso_days_ago(today_iso: str, n: int) -> str:
    d = datetime.fromisoformat(today_iso.replace("Z", ""))
    return (d - timedelta(days=n)).isoformat()


def _key(category: str, scope: str) -> str:
    return f"{category}:{scope}"


def _is_dismissed(db_path, key: str) -> bool:
    with connect(db_path) as c:
        r = c.execute("SELECT dismissed_at FROM dismissed_tips WHERE tip_key=?", (key,)).fetchone()
    if not r:
        return False
    return (time.time() - r["dismissed_at"]) < 14 * 86400


def dismiss_tip(db_path, key: str) -> None:
    with connect(db_path) as c:
        c.execute(
            "INSERT OR REPLACE INTO dismissed_tips (tip_key, dismissed_at) VALUES (?, ?)",
            (key, time.time()),
        )
        c.commit()


def cache_discipline_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    today_iso = today_iso or datetime.utcnow().isoformat()
    since = _iso_days_ago(today_iso, 7)
    sql = """
      SELECT project_slug,
             SUM(cache_read_tokens) AS cr,
             SUM(input_tokens + cache_create_5m_tokens + cache_create_1h_tokens) AS rebuild
        FROM messages
       WHERE type='assistant' AND timestamp >= ?
       GROUP BY project_slug
       HAVING (cr + rebuild) > 100000
    """
    out = []
    with connect(db_path) as c:
        for row in c.execute(sql, (since,)):
            total = (row["cr"] or 0) + (row["rebuild"] or 0)
            hit = (row["cr"] or 0) / total if total else 0
            if hit < 0.40:
                key = _key("cache", row["project_slug"])
                if _is_dismissed(db_path, key):
                    continue
                out.append({
                    "key": key,
                    "category": "缓存",
                    "title": f"{row['project_slug']} 的缓存命中率偏低",
                    "body": f"最近 7 天缓存命中率为 {hit*100:.0f}%。频繁重启上下文会反复重建缓存。可以考虑延长单次会话，或减少上下文重置次数。",
                    "scope": row["project_slug"],
                })
    return out


def repeated_target_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    today_iso = today_iso or datetime.utcnow().isoformat()
    since = _iso_days_ago(today_iso, 7)
    out = []
    with connect(db_path) as c:
        for row in c.execute("""
          SELECT target, COUNT(*) AS n, COUNT(DISTINCT session_id) AS sessions
            FROM tool_calls
           WHERE tool_name IN ('Read','Edit','Write') AND timestamp >= ?
           GROUP BY target HAVING n > 10
           ORDER BY n DESC LIMIT 10
        """, (since,)):
            key = _key("repeat-file", row["target"] or "?")
            if _is_dismissed(db_path, key):
                continue
            out.append({
                "key": key, "category": "重复文件",
                "title": f"{row['target']} 被读取了 {row['n']} 次",
                "body": f"最近 7 天，这个文件在 {row['sessions']} 个会话中被打开了 {row['n']} 次。把摘要放进项目说明，或每个会话只读取一次，可以减少重复消耗。",
                "scope": row["target"],
            })
        for row in c.execute("""
          SELECT target, COUNT(*) AS n
            FROM tool_calls
           WHERE tool_name='Bash' AND timestamp >= ?
           GROUP BY target HAVING n > 15
           ORDER BY n DESC LIMIT 10
        """, (since,)):
            key = _key("repeat-bash", row["target"] or "?")
            if _is_dismissed(db_path, key):
                continue
            out.append({
                "key": key, "category": "重复命令",
                "title": f"`{row['target']}` 运行了 {row['n']} 次",
                "body": f"最近 7 天，这条 Bash 命令运行了 {row['n']} 次。可以考虑使用 watch 参数或 shell 别名。",
                "scope": row["target"],
            })
    return out


def codex_right_size_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    today_iso = today_iso or datetime.utcnow().isoformat()
    since = _iso_days_ago(today_iso, 7)
    pairs = [
        ("gpt-5.6-sol", "gpt-5.6-terra"),
        ("gpt-5.6-terra", "gpt-5.6-luna"),
        ("gpt-5.5", "gpt-5.4"),
        ("gpt-5.4", "gpt-5.4-mini"),
    ]
    pricing = load_pricing(PRICING_JSON)
    out = []
    with connect(db_path) as c:
        for source, target in pairs:
            rows = [dict(row) for row in c.execute("""
              SELECT timestamp, input_tokens, output_tokens, cache_read_tokens,
                     cache_create_5m_tokens, cache_create_1h_tokens
                FROM messages
               WHERE type='assistant' AND model = ?
                 AND output_tokens < 500 AND is_sidechain = 0
                 AND timestamp >= ?
            """, (source, since))]
            if len(rows) < 10:
                continue
            source_cost = sum(
                cost_for(source, row, pricing, at=row["timestamp"])["usd"] for row in rows
            )
            target_cost = sum(
                cost_for(target, row, pricing, at=row["timestamp"])["usd"] for row in rows
            )
            savings = source_cost - target_cost
            if savings < 1.0:
                continue
            key = _key("codex-right-size", f"{source}-short-turns-7d")
            if _is_dismissed(db_path, key):
                continue
            out.append({
                "key": key,
                "category": "模型选择",
                "title": f"{len(rows)} 个短 {source} 轮次可评估改用 {target}",
                "body": f"最近 7 天，低于 500 输出 tokens 的 {source} 轮次约花费 ${source_cost:.2f}；按 {target} 单价约为 ${target_cost:.2f}，可节省约 ${savings:.2f}。这是 Codex 成本提示；复杂调试、架构、安全审查仍应优先保留高能力模型。",
                "scope": f"{source}-short-turns-7d",
            })
    return out


# Keep the historical public name used by the CLI and integrations.
right_size_tips = codex_right_size_tips


def outlier_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    today_iso = today_iso or datetime.utcnow().isoformat()
    since = _iso_days_ago(today_iso, 7)
    out = []
    with connect(db_path) as c:
        big = c.execute("""
          SELECT COUNT(*) AS n, AVG(result_tokens) AS avg_t
            FROM tool_calls
           WHERE tool_name IN ('_tool_result','_unallocated')
             AND result_tokens > 50000 AND timestamp >= ?
        """, (since,)).fetchone()
        if big and (big["n"] or 0) >= 5:
            key = _key("tool-bloat", "result-50k+")
            if not _is_dismissed(db_path, key):
                out.append({
                    "key": key, "category": "工具输出过大",
                    "title": f"本周有 {big['n']} 个工具结果超过 50k tokens",
                    "body": f"平均大小为 {int(big['avg_t']):,} tokens。长 Bash 输出可以通过 head/tail 截断，也可以要求更窄范围的文件读取。",
                    "scope": "result-50k+",
                })
        for row in c.execute("""
          SELECT agent_id, COUNT(*) AS n,
                 AVG(input_tokens+output_tokens) AS mean_t,
                 MAX(input_tokens+output_tokens) AS max_t
            FROM messages
           WHERE is_sidechain=1 AND agent_id IS NOT NULL AND timestamp >= ?
           GROUP BY agent_id HAVING n >= 10
        """, (since,)):
            if (row["max_t"] or 0) > 6 * (row["mean_t"] or 1) and (row["max_t"] or 0) > 50_000:
                key = _key("subagent-outlier", row["agent_id"])
                if _is_dismissed(db_path, key):
                    continue
                out.append({
                    "key": key, "category": "子代理异常值",
                    "title": f"子代理 {row['agent_id']} 存在高消耗异常值",
                    "body": f"最大一次调用使用 {int(row['max_t']):,} tokens，平均为 {int(row['mean_t']):,}。建议检查这些高消耗调用做了什么不同的事。",
                    "scope": row["agent_id"],
                })
    return out


def codex_skill_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    today_iso = today_iso or datetime.utcnow().isoformat()
    since = _iso_days_ago(today_iso, 7)
    out = []
    with connect(db_path) as c:
        rows = c.execute("""
          SELECT target AS skill, COUNT(*) AS n, COUNT(DISTINCT session_id) AS sessions
            FROM tool_calls
           WHERE tool_name='Skill' AND target IS NOT NULL AND target != '' AND timestamp >= ?
           GROUP BY target
           ORDER BY n DESC
           LIMIT 20
        """, (since,)).fetchall()
    for row in rows:
        tokens = tokens_for(row["skill"])
        if not tokens or tokens < 2500 or (row["n"] or 0) < 3:
            continue
        estimated = tokens * (row["n"] or 0)
        if estimated < 15000:
            continue
        key = _key("codex-skill-context", row["skill"])
        if _is_dismissed(db_path, key):
            continue
        out.append({
            "key": key,
            "category": "技能上下文",
            "title": f"{row['skill']} 技能本周加载 {row['n']} 次",
            "body": f"该 SKILL.md 约 {tokens:,} tokens，最近 7 天跨 {row['sessions']} 个会话加载，粗略上下文量约 {estimated:,} tokens。若它是固定项目规则，可以考虑把稳定部分沉淀到项目说明，技能只保留操作流程。",
            "scope": row["skill"],
        })
    return out


def all_tips(db_path, today_iso: Optional[str] = None) -> List[dict]:
    return [
        *cache_discipline_tips(db_path, today_iso),
        *repeated_target_tips(db_path, today_iso),
        *right_size_tips(db_path, today_iso),
        *outlier_tips(db_path, today_iso),
        *codex_skill_tips(db_path, today_iso),
    ]
