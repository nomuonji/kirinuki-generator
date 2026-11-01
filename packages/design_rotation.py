"""Rotates the Shorts design template so consecutive uploads never share one look.

The Remotion side (apps/remotion/src/design/registry.ts) implements the templates; this module
only decides which template/colour variant each clip gets. Picks are least-recently-used: every
template is used once before any repeats, and the order inside each cycle is shuffled by a
seed so the channel doesn't show a fixed A→B→C→D→E pattern either. The colour variant inside a
template rotates the same way.

History is a list of {"template", "variant"} dicts, oldest first. The direct lane builds it
from the publish ledger (packages/github_ledger.py) so rotation continues across runs.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable

# Keep in sync with TEMPLATES in apps/remotion/src/design/registry.ts (a test checks this).
TEMPLATE_VARIANTS: dict[str, int] = {
    "gougai": 2,
    "terminal": 3,
    "pop": 3,
    "cinema": 2,
    "note": 2,
}
TEMPLATES = tuple(TEMPLATE_VARIANTS)


def _tiebreak(seed: str, *parts: object) -> str:
    return hashlib.sha256("|".join([seed, *map(str, parts)]).encode("utf-8")).hexdigest()


def _clean_history(history: Iterable[object] | None) -> list[dict]:
    out: list[dict] = []
    for entry in history or []:
        if isinstance(entry, str):
            entry = {"template": entry}
        if not isinstance(entry, dict):
            continue
        template = entry.get("template")
        if template not in TEMPLATE_VARIANTS:
            continue
        try:
            variant = int(entry.get("variant", -1))
        except (TypeError, ValueError):
            variant = -1
        out.append({"template": template, "variant": variant})
    return out


def pick_designs(history: Iterable[object] | None, count: int, seed: str = "") -> list[dict]:
    """Return `count` picks continuing the rotation after `history`.

    Each pick is {"template", "variant", "designSeed"}; designSeed drives small per-clip
    differences inside a template (tilt direction, noise pattern).
    """
    timeline = _clean_history(history)
    picks: list[dict] = []
    for i in range(max(0, count)):
        last_used = {t: -1 for t in TEMPLATES}
        for pos, entry in enumerate(timeline):
            last_used[entry["template"]] = pos
        previous = timeline[-1]["template"] if timeline else None
        cycle = sum(1 for e in timeline if e["template"] == TEMPLATES[0])
        candidates = [t for t in TEMPLATES if t != previous] or list(TEMPLATES)
        template = min(candidates, key=lambda t: (last_used[t], _tiebreak(seed, cycle, t)))

        variants = TEMPLATE_VARIANTS[template]
        variant_used = {v: -1 for v in range(variants)}
        for pos, entry in enumerate(timeline):
            if entry["template"] == template and 0 <= entry["variant"] < variants:
                variant_used[entry["variant"]] = pos
        variant = min(range(variants), key=lambda v: (variant_used[v], _tiebreak(seed, template, v)))

        design_seed = int(_tiebreak(seed, "clip", len(timeline), i)[:8], 16)
        pick = {"template": template, "variant": variant, "designSeed": design_seed}
        picks.append(pick)
        timeline.append({"template": template, "variant": variant})
    return picks


def history_from_env(env=os.environ) -> list[dict]:
    raw = (env.get("KIRINUKI_DESIGN_HISTORY") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return _clean_history(data if isinstance(data, list) else [])


def history_from_ledger(clips: dict) -> list[dict]:
    """Designs of ledger clips that went out (or are queued to), oldest publish slot first."""
    rows = []
    for record in (clips or {}).values():
        design = record.get("design") if isinstance(record, dict) else None
        if not isinstance(design, dict):
            continue
        when = record.get("publishAt") or record.get("attemptedAt") or ""
        rows.append((str(when), design))
    rows.sort(key=lambda row: row[0])
    return _clean_history(design for _, design in rows)[-20:]


def forced_design(env=os.environ) -> dict | None:
    """KIRINUKI_DESIGN_TEMPLATE=<id>[:<variant>] pins every clip (previews, smoke tests)."""
    raw = (env.get("KIRINUKI_DESIGN_TEMPLATE") or "").strip()
    if not raw:
        return None
    template, _, variant = raw.partition(":")
    if template not in TEMPLATE_VARIANTS:
        raise ValueError(f"Unknown KIRINUKI_DESIGN_TEMPLATE {template!r}; choose from {', '.join(TEMPLATES)}")
    try:
        v = int(variant) % TEMPLATE_VARIANTS[template] if variant else 0
    except ValueError:
        v = 0
    return {"template": template, "variant": v}
