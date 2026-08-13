"""Pricing table + plan-aware cost formatting."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .db import connect


def load_pricing(path: Union[str, Path]) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _timestamp(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pricing_cutoffs(pricing: dict) -> list[str]:
    """Return valid UTC cutoffs used to split aggregate usage rows."""
    cutoffs = {
        item["before"]
        for rates in pricing.get("models", {}).values()
        for item in rates.get("history", [])
        if isinstance(item, dict) and _timestamp(item.get("before")) is not None
    }
    return sorted(cutoffs, key=_timestamp)


def _rates_at(rates: dict, at) -> dict:
    moment = _timestamp(at)
    if moment is None:
        return rates
    history = sorted(
        (item for item in rates.get("history", []) if _timestamp(item.get("before")) is not None),
        key=lambda item: _timestamp(item["before"]),
    )
    for item in history:
        if moment < _timestamp(item["before"]):
            return {**rates, **item}
    return rates


def cost_for(model: str, usage: dict, pricing: dict, at=None) -> dict:
    """Return {usd, estimated, breakdown}. usd=None for unknown models."""
    rates = pricing["models"].get(model)
    if rates is None:
        return {"usd": None, "estimated": True, "breakdown": {}}
    rates = _rates_at(rates, at)

    token_keys = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cache_read": "cache_read_tokens",
        "cache_create_5m": "cache_create_5m_tokens",
        "cache_create_1h": "cache_create_1h_tokens",
    }
    bd = {
        name: usage[key] * rates[name] / 1_000_000
        for name, key in token_keys.items()
    }

    threshold = rates.get("long_context_threshold")
    if threshold:
        long_tokens = {
            name: usage.get(f"long_context_{key}", 0)
            for name, key in token_keys.items()
        }
        if "long_context_input_tokens" not in usage:
            total_input = sum(usage[token_keys[name]] for name in token_keys if name != "output")
            if total_input > threshold:
                long_tokens = {name: usage[key] for name, key in token_keys.items()}

        input_multiplier = rates["long_context_input_multiplier"] - 1
        output_multiplier = rates["long_context_output_multiplier"] - 1
        for name in ("input", "cache_read", "cache_create_5m", "cache_create_1h"):
            bd[name] += long_tokens[name] * rates[name] * input_multiplier / 1_000_000
        bd["output"] += long_tokens["output"] * rates["output"] * output_multiplier / 1_000_000

    return {"usd": round(sum(bd.values()), 6), "estimated": False, "breakdown": bd}


def get_plan(db_path: Union[str, Path], default: str = "api") -> str:
    with connect(db_path) as c:
        row = c.execute("SELECT v FROM plan WHERE k='plan'").fetchone()
    return row["v"] if row else default


def set_plan(db_path: Union[str, Path], plan: str) -> None:
    with connect(db_path) as c:
        c.execute("INSERT OR REPLACE INTO plan (k, v) VALUES ('plan', ?)", (plan,))
        c.commit()


def format_for_user(api_cost_usd: float, plan: str, pricing: dict) -> dict:
    p = pricing["plans"].get(plan, pricing["plans"]["api"])
    if plan == "api" or p["monthly"] == 0:
        return {"display_usd": api_cost_usd, "subtitle": None, "subscription_usd": None}
    return {
        "display_usd":      api_cost_usd,
        "subtitle":         f"You pay ${p['monthly']}/mo on {p['label']}",
        "subscription_usd": p["monthly"],
    }
