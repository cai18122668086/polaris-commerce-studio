"""MG component catalogue, parameter validation and brand palette (W4, v3).

Components are rendered by ``runtime.html`` (anime.js 4.5.0, MIT) in the
existing headless Chromium. Every text parameter must be verbatim speech of
the cue's sentences (punctuation ignored) — no rewritten or invented copy.
"""

from __future__ import annotations

import re
from typing import Any

from .text import is_quote, plain

CATALOG_VERSION = "mg-catalog/2"

# 只在「人物铺满画面、背景层没有模板信息卡」的成套模板上开放 MG（总控 11-28 验收）：
# 其它模板把卡片画在背景层，图层时间线看不到，MG 会压到信息卡上。
MG_TEMPLATES = frozenset(
    {
        "bihuo-08-v1",
        "bihuo-13-v1",
        "bihuo-15-v1",
        "bihuo-32-v1",
        "bihuo-36-v1",
        "bihuo-47-v1",
    }
)
MG_UNSUPPORTED_REASON = "此模板画面已有信息卡，暂不支持 MG"
# 卡片只放短标题/关键词：整句说明会和同一时刻的字幕重复。
DROPPED_FIELDS = frozenset({"desc", "label", "note"})
PROMPT_EXCLUDED = frozenset({"quote_card"})  # 金句卡就是整句，必然和字幕重复
FULLSCREEN_MAX_MS = 2500
MIN_MS, MAX_MS = 1600, 5000

# Brand tokens (plan §5.4). No blue / purple anywhere.
TOKENS = {
    "ink": "#151311",
    "paper": "#F4F0E9",
    "stone": "#8C857C",
    "ember": "#D9572B",
    "amber": "#E9893A",
    "gold": "#B8955A",
}
STYLES: dict[str, dict[str, str]] = {
    # 暖纸：米白卡片、墨色字、熔橙强调
    "paper": {
        "label": "暖纸",
        "bg": TOKENS["paper"],
        "fg": TOKENS["ink"],
        "accent": TOKENS["ember"],
        "sub": TOKENS["stone"],
        "line": TOKENS["ink"],
    },
    # 墨白：墨色卡片、米白字、琥珀强调
    "ink": {
        "label": "墨白",
        "bg": TOKENS["ink"],
        "fg": TOKENS["paper"],
        "accent": TOKENS["amber"],
        "sub": TOKENS["gold"],
        "line": TOKENS["paper"],
    },
    # 熔光：熔橙卡片、米白字、墨色强调
    "ember": {
        "label": "熔光",
        "bg": TOKENS["ember"],
        "fg": TOKENS["paper"],
        "accent": TOKENS["ink"],
        "sub": TOKENS["paper"],
        "line": TOKENS["paper"],
    },
}

# size = card box at 1080×1920; fullscreen components cover the frame.
COMPONENTS: dict[str, dict[str, Any]] = {
    "data_callout": {
        "label": "数据强调",
        "use": "句子里有数字/倍数/时长/百分比",
        "fields": {"value": "数字原文≤8", "unit": "单位≤4"},
        "size": (840, 400),
    },
    "feature_card": {
        "label": "卖点卡",
        "use": "一个具体卖点",
        "fields": {"title": "卖点关键词≤8，不要整句"},
        "size": (840, 300),
    },
    "checklist": {
        "label": "要点清单",
        "use": "并列的 2-4 个要点",
        "fields": {"items": "2-4 条，每条≤10"},
        "size": (840, 520),
    },
    "compare_split": {
        "label": "对比卡",
        "use": "以前/现在、A/B 对比",
        "fields": {
            "left_label": "左标题≤6",
            "left": "左内容≤10",
            "right_label": "右标题≤6",
            "right": "右内容≤10",
        },
        "size": (900, 420),
    },
    "step_progress": {
        "label": "步骤条",
        "use": "第一步/第二步/最后",
        "fields": {"steps": "2-4 步，每步≤6"},
        "size": (900, 300),
    },
    "quote_card": {
        "label": "金句",
        "use": "结论、金句",
        "fields": {"text": "金句≤24"},
        "size": (840, 380),
    },
    "price_tag": {
        "label": "价格签",
        "use": "价格、优惠",
        "fields": {"price": "价格数字≤8"},
        "size": (640, 300),
    },
    "title_reveal": {
        "label": "标题揭示",
        "use": "开场或章节大标题（全屏，≤2.5 秒）",
        "fields": {"text": "标题≤14"},
        "size": (1080, 1920),
        "fullscreen": True,
    },
}
LIMITS = {
    "value": 8,
    "unit": 4,
    "label": 12,
    "title": 8,
    "desc": 18,
    "left_label": 6,
    "left": 10,
    "right_label": 6,
    "right": 10,
    "text": 24,
    "price": 8,
    "note": 10,
}
REQUIRED = {
    "data_callout": ("value",),
    "feature_card": ("title",),
    "compare_split": ("left", "right"),
    "quote_card": ("text",),
    "price_tag": ("price",),
    "title_reveal": ("text",),
}
LISTS = {"checklist": ("items", 2, 4, 10), "step_progress": ("steps", 2, 4, 6)}
_NUMERIC = re.compile(r"^[0-9一二两三四五六七八九十百千万.¥￥%+]+$")


def box_size(component: str, params: dict[str, Any]) -> tuple[int, int]:
    """Card box at 1080×1920; list cards grow with their item count."""
    width, height = COMPONENTS[component]["size"]
    if component == "checklist":
        height = 88 + 96 * len(params.get("items") or [])
    return width, height


def prompt_catalog() -> dict[str, Any]:
    return {
        name: {"use": spec["use"], "fields": spec["fields"]}
        for name, spec in COMPONENTS.items()
        if name not in PROMPT_EXCLUDED
    }


def template_supported(template_id: str | None) -> bool:
    return template_id in MG_TEMPLATES


def _text(value: Any) -> str:
    return (
        re.sub(r"\s+", "", str(value)) if isinstance(value, (str, int, float)) else ""
    )


def validate_params(
    component: str, params: dict[str, Any], source: str
) -> dict[str, Any] | None:
    """Normalised params, or None when anything is invented/too long/missing."""
    if component not in COMPONENTS or not isinstance(params, dict):
        return None
    if component in PROMPT_EXCLUDED:
        return None
    params = {k: v for k, v in params.items() if k not in DROPPED_FIELDS}
    allowed = set(COMPONENTS[component]["fields"])
    if set(params) - allowed:
        return None
    if component in LISTS:
        key, low, high, width = LISTS[component]
        items = params.get(key)
        if not isinstance(items, list) or not low <= len(items) <= high:
            return None
        cleaned = [_text(item) for item in items]
        if any(
            not item or len(plain(item)) > width or not is_quote(item, source)
            for item in cleaned
        ):
            return None
        return {key: cleaned}
    out: dict[str, Any] = {}
    for key in allowed:
        value = _text(params.get(key, ""))
        if not value:
            if key in REQUIRED.get(component, ()):
                return None
            continue
        if len(plain(value)) > LIMITS[key] or not is_quote(value, source):
            return None
        out[key] = value
    if component in ("data_callout", "price_tag"):
        number = out.get("value") or out.get("price") or ""
        if not _NUMERIC.match(number):
            return None
    if not COMPONENTS[component].get("fullscreen") and any(
        _whole_clause(str(value), source)
        for key, value in out.items()
        if key not in ("value", "unit", "price")
    ):
        return None
    return out


def _whole_clause(text: str, source: str) -> bool:
    """A card repeating a whole spoken clause duplicates the caption below it."""
    clauses = {plain(c) for c in re.split(r"[，。！？!?；;,.\s]+", source) if c}
    return plain(text) in clauses


def cue_window(
    component: str, start_ms: int, end_ms: int, duration_ms: int
) -> tuple[int, int] | None:
    """Display window: lead 120 ms, tail 200 ms, clamped; fullscreen ≤2.5 s."""
    start = max(0, start_ms - 120)
    end = min(duration_ms, end_ms + 200)
    if COMPONENTS[component].get("fullscreen"):
        end = min(end, start + FULLSCREEN_MAX_MS)
        return (start, end) if end - start >= 1200 else None
    if end - start < MIN_MS:
        end = min(duration_ms, start + MIN_MS)
    end = min(end, start + MAX_MS)
    return (start, end) if end - start >= 1200 else None
