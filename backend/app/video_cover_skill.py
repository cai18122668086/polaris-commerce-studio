"""Read the cover skill's prompt template and dimension tables at runtime.

The rules belong to ``backend/skill_sources/video-cover-douyin-xhs`` (adapted
from the MIT projects baoyu-skills and directors-chair, see SOURCES.md): edit
the skill files, not this module.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SKILL_ID = "video-cover-douyin-xhs"
SKILL_ROOT = Path(__file__).resolve().parents[1] / "skill_sources" / SKILL_ID

LAYOUT_RULES = {
    "top": "Place the person in the middle and lower part of the frame and keep roughly the top third above the head clean and empty.",
    "bottom": "Place the person in the upper and middle part of the frame; below the chest keep a clean, even area.",
    "side_left": "Place the person towards the right side and keep the left half of the frame clean and empty from top to bottom.",
    "side_right": "Place the person towards the left side and keep the right half of the frame clean and empty from top to bottom.",
    "center": "Keep the centre of the frame clean and empty, with the setting or objects around the edges.",
}


class CoverSkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class Dimensions:
    type: str
    palette: str
    mood: str


@lru_cache(maxsize=1)
def skill_version() -> str:
    return (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def prompt_template() -> str:
    text = (SKILL_ROOT / "references/background-prompt.md").read_text(encoding="utf-8")
    parts = text.split("<!-- prompt -->")
    if len(parts) != 3:
        raise CoverSkillError("background-prompt.md must hold exactly one <!-- prompt --> block")
    return parts[1].strip()


@lru_cache(maxsize=1)
def dimension_texts() -> dict[str, str]:
    text = (SKILL_ROOT / "references/background-prompt.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*((?:type|palette|mood)\.[a-z]+)\s*\|\s*(.+?)\s*\|\s*$", text, re.M)
    return dict(rows)


@lru_cache(maxsize=1)
def dimension_tables() -> dict[str, list[tuple[list[str], str]]]:
    """``{"type": [(signals, value), ...], ...}``; an empty signal list is the default row."""

    text = (SKILL_ROOT / "references/dimensions.md").read_text(encoding="utf-8")
    tables: dict[str, list[tuple[list[str], str]]] = {}
    for name in ("type", "palette", "mood"):
        section = re.search(rf"^## .*? {name}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not section:
            raise CoverSkillError(f"dimensions.md has no {name} table")
        rows = []
        for signals, value in re.findall(r"^\|\s*([^|]+?)\s*\|\s*([a-z]+)\s*\|\s*$", section.group(1), re.M):
            if signals in {"信号", "---"}:
                continue
            rows.append(([] if signals == "默认" else [s.strip() for s in signals.split("、") if s.strip()], value))
        tables[name] = rows
    return tables


def choose_dimensions(topic: str, rotate: int = 0) -> Dimensions:
    """First matching row per table; ``rotate`` (换一批) steps the palette."""

    picked: dict[str, str] = {}
    for name, rows in dimension_tables().items():
        default = next(value for signals, value in rows if not signals)
        picked[name] = next(
            (value for signals, value in rows if signals and any(s in topic for s in signals)),
            default,
        )
    if rotate:
        palettes = list(dict.fromkeys(value for _, value in dimension_tables()["palette"]))
        start = palettes.index(picked["palette"])
        picked["palette"] = palettes[(start + rotate) % len(palettes)]
    return Dimensions(**picked)


def zone_key(layout: str, face_on_right: bool) -> str:
    if layout == "side":
        return "side_left" if face_on_right else "side_right"
    return layout


def build_prompt(topic: str, layout_key: str, dims: Dimensions) -> str:
    texts = dimension_texts()
    values = {
        "type": dims.type,
        "type_rule": texts[f"type.{dims.type}"],
        "palette": dims.palette,
        "palette_rule": texts[f"palette.{dims.palette}"],
        "mood": dims.mood,
        "mood_rule": texts[f"mood.{dims.mood}"],
        "layout_rule": LAYOUT_RULES[layout_key],
        # The topic only sets atmosphere; strip quotes so it cannot read as text to draw.
        "topic": re.sub(r"[\"“”'‘’「」『』]", "", topic)[:200],
    }
    return prompt_template().format(**values)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
