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
_TEXT_ITEMS = {11, 16, 19, 26, 40}

# Fixed opening clocks. Fields revealed together share one cue.
_OPENINGS = {
    2: (0, ("opening_title",), "name_card"),
    8: (2, ("topic",), "identity"),
    10: (2, ("title",), "identity"),
    11: (1, ("title",), "creative_options"),
    16: (1, ("title", "subtitle"), "creative_options"),
    19: (4, ("title",), None),
    26: (1, ("title", "subtitle"), "creative_options"),
    27: (0, ("title", "subtitle"), "identity"),
    29: (1, ("title",), "identity"),
    32: (1, ("title",), "identity"),
    34: (0, ("opening_title",), "identity"),
    47: (2, ("title",), None),
}


def _name_card(cfg: dict, key: str | None) -> dict:
    card = cfg.get(key) or {}
    if key == "creative_options":
        card = card.get("identity") or card.get("name_card") or {}
    if card.get("enabled", True) and (card.get("name") or card.get("description")):
        return card
    return {}


def _first_frame(at: float, fps: int) -> int:
    return math.floor(at * fps + 1e-7) + 1


def _opening_actions(number: int, cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    if number in _OPENINGS:
        frame, keys, identity = _OPENINGS[number]
        if any(cfg.get(key) for key in keys) or _name_card(cfg, identity):
            yield frame / fps, "type"
    if number == 9:
        if cfg.get("title") or cfg.get("support"):
            yield cfg["title_events"]["entry"][0] / fps, "type"
        if card := _name_card(cfg, "identity"):
            yield card["entry"][0] / fps, "text"
    elif number == 13:
        if cfg.get("title") or cfg.get("support"):
            yield cfg["title_events"]["entry"][0] / fps, "type"
        if _name_card(cfg, "name_card"):
            yield cfg["identity_events"]["entry"][0] / fps, "text"
    elif number == 14 and _name_card(cfg, "identity"):
        yield 2 / fps, "text"
    elif number == 15:
        if cfg["header"]["enabled"]:
            yield (cfg["header_entry"][0] + 1) / fps, "type"
        if _name_card(cfg, "identity"):
            yield (cfg["identity_clock"][0] + 1) / fps, "text"
    elif number == 19 and cfg.get("subtitle"):
        yield _first_frame(0.50, fps) / fps, "type"
    elif number == 23 and _name_card(cfg, "identity"):
        yield 0, "text"
    elif number == 24:
        for field, event in (("title", "main_entry"), ("support", "support_entry")):
            if cfg.get(field):
                yield cfg["title_events"][event][0] / fps, "type"
        if _name_card(cfg, "name_card"):
            yield cfg["identity_events"]["entry"][0] / fps, "text"
    elif number == 28 and _name_card(cfg, "identity"):
        yield cfg["identity_clock"][0] / fps, "text"
    elif number == 33:
        if cfg.get("title") or cfg.get("subtitle"):
            yield cfg["opening_end"] * 6 / 77, "type"
        if _name_card(cfg, "creative_options") and cfg["opening_end"] > 0.28:
            yield _first_frame(0.28, fps) / fps, "text"
    elif number == 36:
        if cfg.get("title"):
            yield cfg["title_entry"][0] / fps, "type"
        if _name_card(cfg, "identity"):
            yield 2 / fps, "text"
    elif number == 48 and cfg.get("title"):
        yield math.ceil(2 * cfg["opening_end_frame"] / 71) / fps, "type"


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


def _window_actions(number: int, cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    if number == 2:
        spec = cfg["_list_spec"]
        footer = cfg["conclusion"]
        if spec["enabled"] and (cfg["title"] or cfg["items"] or footer["text"]):
            start = cfg["card_times"][0]
            yield _first_frame(start, fps) / fps, "transition"
            yield from (
                (_first_frame(max(start, row["at"]), fps) / fps, "text")
                for row in cfg["items"]
                if row["text"] and row["at"] < cfg["card_exit"][1]
            )
            if footer["text"] and footer["at"] < cfg["card_exit"][1]:
                yield footer["at"], "closing"
        third = cfg["third"]
        if third["items"]:
            yield third["plate_at"], "transition"
            if third.get("title"):
                yield third["title_at"], "type"
            yield from ((row["at"], "text") for row in third["items"] if row["text"])
        return
    chapters = cfg["chapters"]
    for index, scene in enumerate(chapters):
        for i, key in enumerate(("nav", "nav_support")):
            if not scene.get(key) or (
                index and scene[key] == chapters[index - 1].get(key)
            ):
                continue
            if index == 0 and cfg.get("source_warm_frame"):
                frame = 0
            elif number == 3 and index and key == "nav":
                frame = math.ceil(scene["at"] * fps - 1e-7)
            else:
                if number == 3:
                    at = scene["at"] + ((0.36, 0.48)[i] if not index else 0)
                else:
                    at = scene.get(f"{key}_at", scene["at"] + 0.08 if index else 0.20)
                frame = _first_frame(at, fps)
            yield frame / fps, "type"
        yield from (
            (row["enter_at"], "text") for row in scene.get("items", []) if row["text"]
        )
        for row in scene.get("contrast", []):
            yield (row["at"] if number == 3 else row["phase"][0]), "emphasis"
        quote = scene.get("quote") or {}
        for part in ("first", "second"):
            if quote.get(part):
                yield quote[f"{part}_at"], "type"


def _text_cards(number: int, cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    items = [row for row in cfg["text_items"] if row["text"]]
    materials = cfg["materials"]
    conclusion = [
        row for row in (cfg.get("conclusion") or {}).values() if row.get("text")
    ]
    final = cfg["final_start"]
    if number == 26:
        # The renderer queues its information rows until the last picture exits.
        after_gallery = max(
            (row["end"] + 0.28 for row in materials), default=cfg["opening_end"]
        )
        rows = [
            row for row in items if row["slot_id"].startswith(("points-", "features-"))
        ]
        if rows:
            list_end = max(row["end"] + 0.2 for row in rows)
            for index, row in enumerate(rows):
                at = _first_frame(max(after_gallery, row["start"]), fps) / fps
                next_page = (index // 3 + 1) * 3
                if at < min(
                    list_end,
                    rows[next_page]["start"] if next_page < len(rows) else list_end,
                ):
                    yield at, "text"
        return

    duration = cfg["duration"]
    photo_tail = 0.16 if number in {19, 40} else 0.28
    text_tail = {11: 0.24, 16: 0.2, 19: 0.5, 40: 0.16}[number]
    primary_end = (
        max((row["end"] for row in materials), default=cfg["opening_end"])
        if number == 11
        else 0
    )
    late_start = min(
        (row["start"] for row in items if row["start"] >= duration * 0.58),
        default=final,
    )
    gallery_at = max(late_start + 0.8, min(final, late_start + 2))
    seen: set[int] = set()
    for frame in range(math.ceil(duration * fps)):
        t = frame / fps
        if any(row["start"] <= t < row["end"] + photo_tail for row in materials):
            continue
        active = [row for row in items if row["start"] <= t < row["end"] + text_tail]
        action = "text"
        if number == 11:
            if not (t < primary_end and active):
                if t <= cfg["opening_end"] and cfg.get("title"):
                    continue
                if t >= final:
                    active = [
                        row
                        for row in conclusion
                        if row["start"] <= t < row["end"] + 0.2
                    ]
                    action = "closing"
            shown = active[-1:]
        elif number == 16:
            shown = active[-1:] if t < gallery_at else []
            if t >= gallery_at and not materials:
                shown = [row for row in conclusion if row["start"] <= t]
                action = "closing"
        elif number == 19:
            shown = (
                active[-1:]
                if cfg.get("foreground_alpha") and cfg["head_start"] <= t < final
                else []
            )
        else:  # 40: the late card stack is visible only when an early card is absent.
            early = [row for row in active if row["start"] < duration * 0.58]
            shown = (
                early[-1:]
                or [
                    row
                    for row in items
                    if duration * 0.5 <= row["start"] < final
                    and row["start"] <= t < min(final, row["end"] + 2.4)
                ][-2:]
            )
        for row in shown:
            if id(row) not in seen and (
                t > row["start"] or (number == 16 and action == "closing")
            ):
                seen.add(id(row))
                yield t, action


def _layout_actions(number: int, cfg: dict, fps: int) -> Iterator[tuple[float, str]]:
    if number in {2, 3, 4}:
        yield from _window_actions(number, cfg, fps)
    elif number in _TEXT_ITEMS:
        yield from _text_cards(number, cfg, fps)
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
        yield from (
            (row["start"], "text")
            for row in cfg.get("pills", [])
            if row["text"] and row["start"] < cfg["pills_exit"][1]
        )
        for card in (cfg["information"], cfg["second_information"]):
            if card["enabled"]:
                yield card["start"], "transition"
                if card.get("label") and card.get("label_at") is not None:
                    yield card["label_at"], "type"
                yield from ((row["start"], "text") for row in card["items"])
    elif number == 23:
        if cfg["ticker"]["enabled"]:
            yield cfg["ticker_entry_frame"] / fps, "type"
        if cfg["closing"]["enabled"]:
            yield cfg["closing"]["start"], "text"
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
        yield from (
            (min(cfg["opening_end"] - 0.2, 0.24 + index * 0.42), "text")
            for index, row in enumerate(cfg["initial_items"])
            if row["text"]
        )
        if theme["text"]:
            yield _first_frame(theme["start"], fps) / fps, "type"
        if browser.get("lines"):
            yield _first_frame(browser["start"], fps) / fps, "transition"
        if steps.get("title"):
            yield _first_frame(steps["start"], fps) / fps, "transition"
        yield from ((row["start"], "text") for row in steps["items"])
    elif number == 34:
        yield cfg["cut_frame"] / fps, "transition"
        if glyphs := (cfg.get("header") or {}).get("glyph_start"):
            yield glyphs[0] / fps, "type"
    elif number == 36:
        yield cfg["handoff"] / fps, "transition"
        yield cfg["outer_start"] / fps, "closing"
    elif number == 47:
        if cfg.get("support") and cfg["opening_end"] > 0.88:
            yield 22 / fps, "type"
        identity = cfg.get("identity") or {}
        if identity.get("enabled") and (
            identity.get("name") or identity.get("description")
        ):
            yield 4 / fps, "text"
        if cfg.get("iris_at") is not None:
            yield round(cfg["iris_at"] * fps) / fps, "transition"
        yield from ((row["start"], "text") for row in cfg["columns"])
        if cfg["star_count"]:
            yield cfg["stars_at"] + 1 / fps, "confirm"


def suite_actions(template_id: str, cfg: dict[str, Any]) -> list[tuple[float, str]]:
    number = int(template_id.split("-")[1])
    fps = cfg.get("fps", 25)
    events = list(_opening_actions(number, cfg, fps))
    for row in cfg.get("materials", []):
        at = _material_start(number, row, fps)
        if at is not None:
            events.append((at, "media"))
    events.extend(_layout_actions(number, cfg, fps))
    return [(at, action) for at, action in events if math.isfinite(at) and at >= 0]


def apple_actions(cfg: dict) -> list[tuple[float, str]]:
    fps = cfg["fps"]
    actions: list[tuple[float, str]] = []
    if _name_card(cfg, "name_card").get("name"):
        actions.append((0, "text"))
    if cfg.get("subtitle"):
        frame = _first_frame(0.28, fps) if cfg.get("opening_variant") == "B" else 0
        actions.append((frame / fps, "type"))
    if cfg.get("title"):
        frame = _first_frame(0.96, fps) if cfg.get("opening_variant") == "B" else 0
        actions.append((frame / fps, "type"))
    for row in cfg.get("chapters", []):
        if row["text"]:
            actions.append((_first_frame(row["time"], fps) / fps, "text"))
    for panel in cfg.get("information", []):
        inputs = panel["input"]
        events = inputs["events"]
        start = round(panel["start"] * fps)
        roles: list[tuple[int, str]] = []
        if panel["component"] == "T02":
            roles.append((0, "transition"))
            roles.extend((row[0] + 1, "text") for row in events["rows"])
            roles.extend((row[0] + 1, "confirm") for row in events["toggles"])
        elif panel["component"] == "T03":
            roles.append((events["quote"][0] + 1, "transition"))
            roles.extend(
                (events[part][0] + 1, "type")
                for part in ("first", "second")
                if inputs[part]
            )
        elif panel["component"] == "T04":
            roles.extend((row[0] + 1, "text") for row in events["cards"])
        for frame, action in roles:
            at = max(
                (start + frame) / fps, math.ceil(panel["start"] * fps - 1e-7) / fps
            )
            if at < panel["end"] and start + frame < start + events["exit"][1]:
                actions.append((at, action))
    for panel in cfg.get("media", []):
        start = round(panel["start"] * fps)
        for row in panel["input"]["media_entries"]:
            frame = max(
                start + row["start_frame"] + 1,
                round(panel.get("render_from", panel["start"]) * fps),
            )
            if frame <= round(panel["end"] * fps):
                actions.append((frame / fps, "media"))
    return actions


def editorial_actions(resolved: dict) -> list[tuple[float, str]]:
    from .video_editing_editorial_suite import sections

    actions: list[tuple[float, str]] = [(0, "type")] if resolved["title"] else []
    # Some editorial layouts reuse captions as fallback pages. Only explicit
    # non-caption sections and user pictures get an entrance cue.
    if any(
        resolved[key]
        for key in ("chapters", "points", "features", "conclusion", "materials")
    ):
        actions.extend(
            (row["start"], "media" if "image" in row else "text")
            for row in sections(resolved)[1:]
            if row["text"] or "image" in row
        )
    return actions
