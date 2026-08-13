"""Skill catalog: locate SKILL.md files and map slugs to file sizes.

Claude Code skills live at one of:
  ~/.claude/skills/<name>/SKILL.md                     -> slug "<name>"
  ~/.claude/scheduled-tasks/<name>/SKILL.md            -> slug "<name>"
  ~/.claude/plugins/marketplaces/*/plugins/<plugin>/skills/<name>/SKILL.md
      -> registers TWO slugs: "<plugin>:<name>" and "<name>"
      (Claude Code accepts either form in the Skill tool.)

Codex skills live at one of:
  ~/.codex/skills/<name>/SKILL.md
  ~/.agents/skills/<name>/SKILL.md
  ~/.codex/plugins/cache/<market>/<plugin>/<version>/skills/<name>/SKILL.md
  ~/.codex/skill-stack/library/.../<name>/SKILL.md
  ~/.codex/sources/.../<name>/SKILL.md

Sizes are in chars; token estimate is chars // 4 (the same approximation
`scanner._extract_results` uses for tool-result tokens).
"""
from __future__ import annotations

import time
import re
from pathlib import Path
from typing import Dict, Optional

_DEFAULT_ROOTS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".claude" / "scheduled-tasks",
    Path.home() / ".claude" / "plugins",
    Path.home() / ".codex" / "skills",
    Path.home() / ".codex" / "plugins",
    Path.home() / ".codex" / "skill-stack" / "library",
    Path.home() / ".codex" / "sources",
    Path.home() / ".agents" / "skills",
]

_VERSION_RE = re.compile(r"^\d+\.\d+")
_HASH_RE = re.compile(r"^[0-9a-f]{7,}$")
_STRUCTURE_NAMES = {"skills", "plugins", "marketplaces", "cache", ".claude", ".codex", ".agents", ".system", "home", "skill-stack", "library", "sources"}


def _slugs_for(skill_md: Path) -> list[str]:
    """Return the slug(s) a Skill tool invocation could use to load this file.

    Paths vary by install source:
      marketplaces/<m>/plugins/<plugin>/skills/<skill>/SKILL.md
      cache/<m>/<plugin>/<version>/skills/<skill>/SKILL.md
      cache/temp_git_*/skills/<skill>/SKILL.md         (no plugin)
      skills/<skill>/SKILL.md                          (no plugin)
      scheduled-tasks/<skill>/SKILL.md                 (no plugin)

    Strategy: always register the bare skill name. Additionally, walk up from
    `skills/` and register `<ancestor>:<skill>` for every ancestor segment
    that plausibly names a plugin (not a structural/version/temp-dir token).
    Unused slugs are harmless — the user only invokes real ones.
    """
    parts = skill_md.parts
    if "SKILL.md" not in parts or skill_md.name != "SKILL.md":
        return []
    skill_name = skill_md.parent.name
    slugs = {skill_name}
    # Locate the `skills` folder that contains this skill.
    try:
        skills_idx = len(parts) - 1 - parts[::-1].index("skills")
    except ValueError:
        return list(slugs)
    for seg in parts[:skills_idx]:
        if not seg or seg in _STRUCTURE_NAMES:
            continue
        if _VERSION_RE.match(seg):
            continue
        if _HASH_RE.match(seg):
            continue
        if seg.startswith("temp_git_"):
            continue
        if seg.endswith(":") or ":" in seg:  # drive letters like "C:"
            continue
        slugs.add(f"{seg}:{skill_name}")
    return sorted(slugs)


def scan_catalog(roots=None) -> Dict[str, dict]:
    """Return {slug: {path, chars, tokens}} for every SKILL.md found.

    When a slug resolves to multiple files (nested `skills/skills/`), keep the
    entry with the shallowest path — that's the canonical install.
    """
    roots = roots or _DEFAULT_ROOTS
    catalog: Dict[str, dict] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for md in root.rglob("SKILL.md"):
            try:
                chars = md.stat().st_size
            except OSError:
                continue
            entry = {"path": str(md), "chars": chars, "tokens": chars // 4}
            for slug in _slugs_for(md):
                prev = catalog.get(slug)
                if prev is None or len(md.parts) < len(Path(prev["path"]).parts):
                    catalog[slug] = entry
    return catalog


_cache: dict = {"at": 0.0, "data": {}}
_TTL_SECONDS = 60.0


def cached_catalog() -> Dict[str, dict]:
    """scan_catalog() with a simple in-process TTL cache."""
    now = time.time()
    if now - _cache["at"] > _TTL_SECONDS:
        _cache["data"] = scan_catalog()
        _cache["at"] = now
    return _cache["data"]


def tokens_for(slug: str, catalog: Optional[Dict[str, dict]] = None) -> Optional[int]:
    cat = catalog if catalog is not None else cached_catalog()
    info = cat.get(slug)
    return info["tokens"] if info else None
