"""Read the visible action clocks emitted by the native suite compilers."""

import math
from collections.abc import Iterator
from typing import Any

from .bihuo_suite.video_materials import NATIVE_VIDEO

_PAPER_AND_SOFT = {8, 9, 10, 11, 13, 16, 24, 27}
_WINDOW_AND_MATERIAL = {2, 3, 4, 48}
_NATIVE_SUITES = (
    2,
    3,
    4,
    8,
    9,
    10,
    11,
    13,
    14,
    15,
    16,
    19,
    23,
    24,
    26,
    27,
    28,
    29,
    32,
    33,
    34,
    36,
    40,
    47,
    48,
)
SUITE_FAMILIES = {
    f"bihuo-{number:02}-v1": (
        "lifestyle"
        if number in _PAPER_AND_SOFT
        else "application"
        if number in _WINDOW_AND_MATERIAL
        else "news"
    )
    for number in _NATIVE_SUITES
}

_FRAME_MATERIAL = {8, 13, 24, 48}
_TEXT_ITEMS = {11, 16, 19, 26, 33, 40}

# Each entry uses the first native frame of the visible effect.
_TITLE_FRAMES = {
    8: ("topic", 2),
    10: ("title", 4),
    11: ("title", 3),
    13: ("title", 3),
    16: ("title", 3),
    19: ("title", 3),
    24: ("title", 3),
    26: ("title", 3),
    27: ("title", 4),
    29: ("title", 4),
    32: ("title", 4),
    34: ("opening_title", 3),
    36: ("title", 3),
    47: ("title", 3),
    48: ("title", 3),
}


def _material_start(number: int, row: dict, fps: int) -> float | None:
    if number == 15:
        return row["frames"][0] / fps
    if number == 47:
        return float(row["visual_start"])
    if number in _FRAME_MATERIAL:
        return float(row["start"]) / fps
    if number != 9:
        return float(row["start"])
    # The paper template's visible materials use its per-phase card entry.
    return None


def recording_windows(template_id: str, cfg: dict) -> Iterator[tuple[dict, int, float]]:
    if template_id not in NATIVE_VIDEO:
        return
    fps = cfg["fps"]
    for row in cfg["materials"]:
        if row.get("type") == "video":
            span = round((row["end"] - row["start"]) * 1000)
            yield row, span, round(row["start"] * fps) / fps


def _caption_actions(cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    for row in cfg.get("captions", []):
        emphasis = (
            row.get("emphasis_spans")
            or row.get("emphasis")
            or row.get("emphasis_token_spans")
            or row.get("bold")
            or any(line.get("emphasis_spans") for line in row.get("lines", []))
        )
        if not emphasis:
            continue
        if row.get("time"):
            yield row["time"][0], "emphasis"
        elif row.get("range"):
            yield row["range"][0] / fps, "emphasis"
        elif row.get("frames"):
            yield row["frames"][0] / fps, "emphasis"
        elif "first" in row:
            yield row["first"] / fps, "emphasis"


def _window_actions(number: int, cfg: dict) -> Iterator[tuple[float, str]]:
    if number == 2:
        spec = cfg["_list_spec"]
        if spec["enabled"]:
            yield cfg["card_times"][0], "transition"
            yield from ((row["at"], "text") for row in cfg["items"] if row["text"])
        third = cfg["third"]
        if third["items"]:
            yield third["plate_at"], "transition"
            yield from ((row["at"], "text") for row in third["items"] if row["text"])
        return
    for scene in cfg["chapters"]:
        yield from (
            (row["enter_at"], "text") for row in scene.get("items", []) if row["text"]
        )
        for row in scene.get("contrast", []):
            yield (row["at"] if number == 3 else row["phase"][0]), "emphasis"
        quote = scene.get("quote") or {}
        for part in ("first", "second"):
            if quote.get(part):
                yield quote[f"{part}_at"], "type"


def _text_cards(number: int, cfg: dict) -> Iterator[tuple[float, str]]:
    items = cfg["text_items"]
    if number == 26:
        # The feature list opens after the last picture finishes moving.
        after_gallery = max((row["end"] for row in cfg["materials"]), default=0)
        for item in items:
            if item["slot_id"].startswith(("points-", "features-")):
                at = max(after_gallery, item["start"])
                if at < item["end"] + 0.2:
                    yield at, "text"
    else:
        yield from ((item["start"], "text") for item in items)
    if cfg.get("conclusion"):
        yield cfg["final_start"], "closing"


def _layout_actions(number: int, cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    if number in {2, 3, 4}:
        yield from _window_actions(number, cfg)
    elif number in _TEXT_ITEMS:
        yield from _text_cards(number, cfg)
    elif number == 8:
        yield from ((row["start"] / fps, "type") for row in cfg["text_cards"])
    elif number == 9:
        for phase in cfg["phases"]:
            if phase["enabled"]:
                yield (
                    (phase["entry"][0] + 1) / fps,
                    "media" if phase.get("asset_id") else "type",
                )
    elif number == 10:
        if cfg["star_count"]:
            yield cfg["stars_at"] + 1 / fps, "confirm"
        if cfg["wipe_at"] is not None:
            yield cfg["wipe_at"], "transition"
        card = cfg["card"]
        if card["enabled"]:
            yield from ((row["at"], "text") for row in card["items"])
            if card["button"]:
                yield card["button_at"], "closing"
    elif number == 14:
        for card in (cfg["information"], cfg["second_information"]):
            if card["enabled"]:
                yield card["start"], "transition"
                yield from ((row["start"], "text") for row in card["items"])
    elif number == 15 and cfg["header"]["enabled"]:
        yield (cfg["header_entry"][0] + 1) / fps, "type"
    elif number == 23:
        if cfg["ticker"]["enabled"]:
            yield cfg["ticker_entry_frame"] / fps, "type"
        if cfg["closing"]["enabled"]:
            yield cfg["closing"]["button_at"], "closing"
    elif number == 28:
        yield from (
            (row["first"] / fps, "type") for row in cfg["agenda"] if row["text"]
        )
        yield from ((row["start"], "emphasis") for row in cfg["abilities"])
        tool = cfg.get("tool") or {}
        if tool.get("button"):
            yield tool["button_at"], "confirm"
    elif number == 29:
        theme, browser, steps = cfg["theme"], cfg["browser"], cfg["steps"]
        if theme["text"]:
            yield theme["start"], "type"
        if browser.get("lines"):
            yield browser["start"], "transition"
        yield from ((row["start"], "text") for row in steps["items"])
    elif number == 32:
        selected = set(cfg["glyph_caption_ids"])
        yield from (
            (row["time"][0], "type") for row in cfg["captions"] if row["id"] in selected
        )
    elif number == 34:
        yield cfg["cut_frame"] / fps, "transition"
        if glyphs := cfg["header"].get("glyph_start"):
            yield glyphs[0] / fps, "type"
    elif number == 36:
        yield cfg["handoff"] / fps, "transition"
        yield cfg["outer_start"] / fps, "closing"
    elif number == 47:
        yield from ((row["start"], "text") for row in cfg["columns"])
        if cfg["star_count"]:
            yield cfg["stars_at"] + 1 / fps, "confirm"


def suite_actions(template_id: str, cfg: dict[str, Any]) -> list[tuple[float, str]]:
    number = int(template_id.split("-")[1])
    fps = cfg.get("fps", 25)
    events: list[tuple[float, str]] = [(1 / fps, "opening")]
    if number == 33 and (cfg.get("title") or cfg.get("subtitle")):
        events.append((cfg["opening_end"] * 8 / 77, "type"))
    if number in _TITLE_FRAMES:
        key, frame = _TITLE_FRAMES[number]
        if cfg.get(key):
            events.append((frame / fps, "type"))
    for row in cfg.get("materials", []):
        at = _material_start(number, row, fps)
        if at is not None:
            events.append((at, "media"))
    events.extend(_caption_actions(cfg, fps))
    events.extend(_layout_actions(number, cfg, fps))
    return [(at, action) for at, action in events if math.isfinite(at) and at >= 0]
