"""Fixed complete recipes: measured style grammar, variable semantic word clocks."""

from copy import deepcopy
from typing import Any


def _pose(
    time: float,
    matrix: list[list[float]],
    rect: list[float],
    radius: float = 25,
    bg: float = 0,
) -> dict[str, Any]:
    return {
        "time": time,
        "matrix": matrix,
        "rect": rect,
        "radius": radius,
        "background_opacity": bg,
    }


def _transition(
    keys: list[dict[str, Any]],
    start: float,
    old: dict[str, Any],
    new: dict[str, Any],
) -> None:
    for dt, q in [
        (0, 0),
        (0.16, 0.22),
        (0.32, 0.59),
        (0.48, 0.84),
        (0.64, 0.95),
        (0.88, 1),
    ]:
        m = [
            [a * (1 - q) + b * q for a, b in zip(r1, r2, strict=True)]
            for r1, r2 in zip(old["matrix"], new["matrix"], strict=True)
        ]
        r = [a * (1 - q) + b * q for a, b in zip(old["rect"], new["rect"], strict=True)]
        keys.append(
            _pose(
                start + dt,
                m,
                r,
                old["radius"] * (1 - q) + new["radius"] * q,
                old["background_opacity"] * (1 - q) + new["background_opacity"] * q,
            )
        )


def compile_recipe(
    resolved: dict[str, Any],
    *,
    fonts: dict[str, str],
    size: tuple[int, int] = (1080, 1920),
    ffmpeg: str = "ffmpeg",
    source_path: str,
    music: str = "template",
    creative_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    c = creative_options or {}
    fps = 25
    duration = float(resolved["duration"])
    intro = max(1.6, min(float(resolved["opening_end"]), duration - 0.25))
    variant = resolved["body_variant"]
    materials = resolved.get("materials", [])
    points = resolved.get("points", [])
    features = resolved.get("features", [])
    quote = resolved.get("conclusion")
    quote_start = resolved.get("quote_start")
    if variant == "materials" and not materials:
        variant = "points" if points else "speech"
    full = _pose(0, [[1.03, 0, -8], [0, 1.03, 97]], [0, 97, 540, 960], 0, 1)
    small = _pose(0, [[0.307, 0, 187], [0, 0.307, 570]], [199, 606, 342, 796], 14)
    wide = _pose(0, [[0.925, 0, 20], [0, 0.925, 410]], [27, 518, 513, 883])
    upper = _pose(0, [[0.925, 0, 20], [0, 0.925, 368]], [27, 476, 513, 841])
    returned = _pose(0, [[1.02, 0, -5], [0, 1.02, -10]], [0, 0, 540, 960], 0)
    keys = [full]
    _transition(keys, intro, full, small if variant == "materials" else wide)
    if features:
        at = max(intro + 0.92, min(x["start"] for x in features) - 0.16)
        _transition(keys, at, small if variant == "materials" else wide, wide)
    if quote and quote_start is not None:
        at = max(intro + 0.92, float(quote_start))
        _transition(
            keys, at, wide if features or variant != "materials" else small, upper
        )
        last = max(quote["first"]["end"], quote["second"]["end"]) + 0.24
        if duration - last > 0.9:
            _transition(keys, last, upper, returned)
    keys.sort(key=lambda x: x["time"])
    keys = [x for i, x in enumerate(keys) if i == 0 or x["time"] > keys[i - 1]["time"]]
    info_fonts = {
        "title": fonts["main"],
        "body": fonts["caption"],
        "card": fonts["caption_bold"],
        "header": fonts["caption_bold"],
    }
    information = []
    if variant == "points" and points:
        start = max(intro + 0.48, min(x["start"] for x in points) - 0.25)
        end = float(quote_start) if quote_start is not None else duration

        def points_local(x: float) -> int:
            return max(0, round((x - start) * fps))

        n = len(points)
        information.append(
            {
                "component": "T02",
                "start": start,
                "end": end,
                "input": {
                    "fonts": info_fonts,
                    "header": f"{n} 项要点",
                    "items": [x["text"] for x in points],
                    "events": {
                        "rows": [[5 + i * 6, 11 + i * 6] for i in range(n)],
                        "toggles": [
                            [
                                max(12, points_local(x["start"])),
                                max(18, points_local(x["start"]) + 6),
                            ]
                            for x in points
                        ],
                        "exit": [max(0, points_local(end) - 8), points_local(end)],
                    },
                },
            }
        )
    if features:
        start = max(intro + 0.92, min(x["start"] for x in features) - 0.16)
        end = (
            float(quote_start)
            if quote_start is not None
            else min(duration, max(x["end"] for x in features) + 0.4)
        )

        def feature_local(x: float) -> int:
            return max(0, round((x - start) * fps))

        cards = [
            [feature_local(x["start"]), feature_local(x["start"]) + 7] for x in features
        ]
        handoffs = [cards[min(i, len(cards) - 1)] for i in [1, 2]]
        information.append(
            {
                "component": "T04",
                "start": start,
                "end": end,
                "input": {
                    "fonts": info_fonts,
                    "items": [x["text"] for x in features],
                    "events": {
                        "cards": cards,
                        "focus_handoffs": handoffs,
                        "exit": [max(0, feature_local(end) - 8), feature_local(end)],
                    },
                },
            }
        )
    if quote and quote_start is not None:
        start = max(intro + 0.92, float(quote_start))
        end = min(duration, max(quote["first"]["end"], quote["second"]["end"]) + 0.24)
        second = max(8, round((quote["second"]["start"] - start) * fps))
        length = round((end - start) * fps)
        information.append(
            {
                "component": "T03",
                "start": start,
                "end": end,
                "input": {
                    "fonts": info_fonts,
                    "first": quote["first"]["text"],
                    "second": quote["second"]["text"],
                    "events": {
                        "quote": [0, 5],
                        "first": [3, 10],
                        "second": [second, second + 7],
                        "exit": [max(15, length - 8), length],
                    },
                },
            }
        )
    media = []
    if variant == "materials" and materials:
        start = materials[0]["start"]
        end = min(
            duration,
            float(quote_start)
            if quote_start is not None
            else min(x["start"] for x in features)
            if features
            else duration,
        )
        entries = []
        for i, item in enumerate(materials):
            entry = {
                "id": item["asset_id"],
                "path": item["path"],
                "type": item["kind"],
                "start_frame": round((item["start"] - start) * fps),
                "source_in": 0,
                "source_out": max(0, item["duration"] - 1 / 30)
                if item["kind"] == "video"
                else 0,
                "end_policy": "hold",
                "speed": 1,
                "fit": "cover",
                "anchor": [0.5, 0.5],
                "rect": [21, 93, 519, 582] if i == 0 else [21, 93, 519, 410],
                "radius": 14,
                "entry_frames": 9,
                "entry_blur": 10,
                "audio": "muted",
            }
            if i + 1 < len(materials):
                col = i % 3
                entry.update(
                    demote_frame=round((materials[i + 1]["start"] - start) * fps),
                    demote_frames=13,
                    thumbnail_rect=[21 + 169 * col, 419, 180 + 169 * col, 583],
                )
            entries.append(entry)
        media.append(
            {
                "start": start,
                "render_from": start,
                "end": end + 0.24,
                "input": {
                    "media_entries": entries,
                    "exit": {
                        "start_frame": max(0, round((end - start) * fps) - 12),
                        "end_frame": round((end - start) * fps) + 6,
                        "scale": 1.12,
                        "blur": 4,
                        "anchor": [270, 340],
                    },
                },
            }
        )
    captions = deepcopy(resolved.get("captions", []))
    caption_colors = [{"time": 0, "color": "white"}]
    if variant == "materials":
        caption_colors.append({"time": intro + 0.32, "color": "black"})
        takeover = min(x["start"] for x in features) if features else quote_start
        if takeover is not None:
            caption_colors.append({"time": float(takeover) + 0.32, "color": "white"})
    for row in captions:
        row["color"] = (
            "black"
            if variant == "materials"
            and intro
            <= row["time"][0]
            < (
                min(x["start"] for x in features)
                if features
                else float(quote_start)
                if quote_start is not None
                else duration
            )
            else "white"
        )
    cfg = {
        "schema_version": "apple-minimal-render/1",
        "size": list(size),
        "fps": fps,
        "duration": duration,
        "source": source_path,
        "source_in": 0,
        "ffmpeg": ffmpeg,
        "fonts": fonts,
        "title": c.get("title", "").strip() or resolved.get("title", ""),
        "subtitle": c.get("subtitle", "").strip() or resolved.get("subtitle", ""),
        "opening_end": intro,
        "opening_variant": "B",
        "opening_color": [249, 248, 246],
        "stage_color": [254, 252, 255],
        "visual_keys": keys,
        "captions": captions,
        "caption_color_events": caption_colors,
        "chapters": resolved.get("chapters", []),
        "media": media,
        "information": information,
        "name_card": c.get("name_card"),
        "music": music,
        "cover": c.get("cover", "auto"),
        "evidence_frames": [
            round(x * fps)
            for x in [
                0,
                min(1.6, duration - 0.04),
                intro,
                min(duration - 0.04, intro + 0.88),
            ]
        ],
    }
    return cfg
