"""Versioned display fixes around frozen native recipes and recorded speech.

Only compiled display parameters change. Source words, material assignments,
FA clocks and saved plans remain intact. Old payloads without this policy keep
their original execution; native bundle identities are never rewritten.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..video_editing_captioning import text_boundaries

VERSION = "bihuo-conditional-layout/1"
TARGETS = {"bihuo-03-v1", "bihuo-08-v1", "bihuo-09-v1", "bihuo-13-v1"}


def identity() -> dict:
    return {
        "version": VERSION,
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


@lru_cache(maxsize=512)
def _label(text: str, path: str, width: float, sizes: tuple, rows: int) -> dict:
    from PIL import ImageFont

    safe, preferred = text_boundaries(text)
    cuts = sorted(safe - {0, len(text)})
    for size in sizes:
        face = ImageFont.truetype(path, size)
        for count in range(1, rows + 1):
            choices = []
            for breaks in combinations(cuts, count - 1):
                edges = (0, *breaks, len(text))
                lines = [text[a:b] for a, b in zip(edges, edges[1:], strict=False)]
                widths = [face.getlength(line) for line in lines]
                if max(widths, default=0) <= width:
                    choices.append(
                        (
                            (
                                sum(c not in preferred for c in breaks),
                                max(widths),
                                max(widths) - min(widths),
                            ),
                            lines,
                        )
                    )
            if choices:
                return {"lines": min(choices, key=lambda x: x[0])[1], "size": size}
    raise ValueError("Step label needs a separately validated pagination layout")


def prepare(payload: dict) -> dict:
    """Compile deterministic layout using the already resolved native input."""
    template = payload.get("template_id")
    if template not in TARGETS:
        return payload
    cfg = copy.deepcopy(payload["config"])
    policy: dict[str, Any] = identity()
    if template == "bihuo-03-v1":
        for scene in cfg["chapters"]:
            items = scene.get("items", [])
            if not items:
                continue
            width = min(300, (782 - 50 * (len(items) - 1)) / len(items)) - 30
            for item in items:
                # Explicit lines retain the full source-backed label, including
                # punctuation; neither ellipses nor shortened wording are used.
                item["display_horizontal"] = _label(
                    item["text"],
                    cfg["fonts"]["bold"],
                    width,
                    (36, 34, 32, 30, 28),
                    3,
                )
                item["display_vertical"] = _label(
                    item["text"],
                    cfg["fonts"]["body"],
                    220,
                    (28, 26, 24),
                    2,
                )
    elif template == "bihuo-08-v1":
        policy["provided_image_text_zone"] = [60, 70, 1020, 490]
    elif template == "bihuo-09-v1" and not cfg["materials"]:
        phases = sorted(cfg["phases"], key=lambda row: row["entry"][0])
        quote = cfg["resolved_plan"].get("quote_start")
        closing = round(quote * 25) if quote is not None else cfg["fade_start"]
        for i, phase in enumerate(phases):
            original = copy.deepcopy(phase)
            next_start = phases[i + 1]["entry"][0] if i + 1 < len(phases) else closing
            end = max(phase["exit"][0], next_start)
            phase["spoken_display_events"] = original
            phase["exit"] = [end, min(cfg["frame_count"] - 1, end + 9)]
            phase["background_exit"] = [end, min(cfg["frame_count"] - 1, end + 11)]
        cfg["phases"] = phases
        policy["hold_points_between_spoken_spans"] = True
    elif template == "bihuo-13-v1":
        policy["opening_presenter_top"] = 380 if cfg["support"].strip() else 276
    cfg["conditional_layout"] = policy
    return {**payload, "config": cfg}


def _steps(native: Any, cfg: dict, t: float, scene: dict) -> Image.Image:
    items = scene.get("items", [])
    layer = native.blank(cfg)
    if not items:
        return layer
    material = native.material_at(cfg, t) is not None
    current = max([-1] + [i for i, item in enumerate(items) if item["at"] <= t])
    gap = 50 if len(items) > 1 else 0
    width = min(300, (782 - gap * (len(items) - 1)) / len(items))
    left = (1080 - len(items) * width - (len(items) - 1) * gap) / 2
    k = cfg["size"][0] / 1080
    rows = max(len(x["display_horizontal"]["lines"]) for x in items)
    for i, item in enumerate(items):
        row = native.blank(cfg)
        draw = ImageDraw.Draw(row)
        active = i == current
        q = native.ease(item["enter_at"], item["clear_at"], t)
        x, y, w, h = (
            (148, 1080 + i * 94, 300, 84)
            if material
            else (
                left + i * (width + gap),
                1069,
                width,
                210 if rows == 1 else 260,
            )
        )
        color = native.BLUE if active else native.BLACK
        native.rect(
            draw,
            [x, y, x + w, y + h],
            k,
            (217, 224, 241, 255) if active else "white",
            14 if material else 24,
        )
        if material:
            native.put(
                row,
                cfg,
                f"{i + 1:02}",
                20,
                x + 18,
                y + 12,
                native.BLUE if active else native.GRAY,
            )
            display = item["display_vertical"]
            for j, text in enumerate(display["lines"]):
                native.put(
                    row,
                    cfg,
                    text,
                    display["size"],
                    x + 65,
                    y + (29 if len(display["lines"]) == 1 else 12) + j * 32,
                    color,
                    max_width=220,
                )
        else:
            native.put(
                row,
                cfg,
                f"{i + 1:02}",
                28,
                x + w / 2,
                y + 25,
                native.BLUE if active else native.GRAY,
                "center",
            )
            if active:
                draw.ellipse(
                    (
                        (x + w / 2 - 30) * k,
                        (y + 64) * k,
                        (x + w / 2 + 30) * k,
                        (y + 124) * k,
                    ),
                    fill=native.BLUE,
                )
            native.icon(
                row,
                cfg,
                "clock" if i == 2 else "list",
                x + w / 2 - 11,
                y + 83,
                22,
                (255, 255, 255, 255) if active else native.BLUE,
            )
            display = item["display_horizontal"]
            for j, text in enumerate(display["lines"]):
                native.put(
                    row,
                    cfg,
                    text,
                    display["size"],
                    x + w / 2,
                    y + (148 if rows == 1 else 138) + j * 38,
                    color,
                    "center",
                    max_width=w - 30,
                )
        layer.alpha_composite(native.fade(row, q, (1 - q) * 7 * k))
        if i and q > 0 and not material:
            arrow = native.blank(cfg)
            native.icon(arrow, cfg, "arrow", x - gap * 0.74, y + 96, 22, native.GRAY)
            layer.alpha_composite(native.fade(arrow, q))
    return layer


def _photo_text(native: Any, original: Any, cfg: dict, n: int, out: dict) -> None:
    mat = native.match(cfg)
    if not mat or not mat.get("path"):
        original(cfg, n, out)
        return
    # Preserve native photo, affine entry/exit and foreground roles. Text is
    # carried on its own dark header above the sharp image, never over its ink.
    original({**cfg, "material_texts": []}, n, out)
    f = native.native_frame(n, cfg)
    if not native.has_scene(cfg) or not 79 <= f < 217:
        return
    texts = [str(s).strip() for s in cfg.get("material_texts", []) if str(s).strip()]
    if not texts:
        return
    tile = native.blank()
    zone = cfg["conditional_layout"]["provided_image_text_zone"]
    ImageDraw.Draw(tile).rounded_rectangle(
        tuple(zone), radius=24, fill=(6, 16, 24, 245)
    )
    layouts = [
        _label(s, cfg["fonts"]["body"], 880, (70, 64, 58, 52, 46, 40), 2) for s in texts
    ]
    total = sum(len(v["lines"]) * (v["size"] + 12) + 14 for v in layouts) - 14
    if total > zone[3] - zone[1] - 32:
        raise ValueError("Material header exceeds its separate text region")
    y = zone[1] + (zone[3] - zone[1] - total) / 2
    for layout in layouts:
        for text in layout["lines"]:
            im = native.text_image(
                text, cfg["fonts"]["body"], layout["size"], (255, 255, 255, 255)
            )[0]
            tile.alpha_composite(im, (round((1080 - im.width) / 2), round(y)))
            y += layout["size"] + 12
        y += 14
    q = native.interp(f, [(79, 0.35), (80, 0.65), (81, 0.85), (82, 0.97), (83, 1)])
    q *= native.interp(
        f,
        [
            (79, 1),
            (208, 1),
            (209, 0.75),
            (210, 0.55),
            (211, 0.4),
            (212, 0.28),
            (213, 0.18),
            (214, 0.1),
            (215, 0.055),
            (216, 0.025),
        ],
    )
    # Screen-space header stays inside the reading area during the native atlas
    # drift; applying its affine transform here can move the first line offscreen.
    out["material_text"] = native.op(tile, q)


def _text_panels(native: Any, cfg: dict, n: int) -> tuple[dict, list]:
    roles = {}
    metrics = []
    for i, scene in enumerate(cfg["phases"]):
        for key in ("blur_material", "material", "info_plate", "info_text"):
            roles[f"{key}_{i}"] = native.blank()
        q = native.phase(cfg, i, n)
        if q <= 0:
            continue
        rect = [530, 640, 1026, 1020]
        plate = native.blank()
        ImageDraw.Draw(plate).rounded_rectangle(
            tuple(rect),
            radius=26,
            fill=(244, 233, 213, 255),
            outline=(252, 249, 239, 255),
            width=3,
        )
        words = native.blank()
        texts = [
            s.strip() for s in (scene["note_title"], scene["note_detail"]) if s.strip()
        ]
        layouts = [
            _label(s, cfg["fonts"]["title"], 432, (64, 58, 52, 46, 40, 34), 3)
            for s in texts
        ]
        height = sum(len(v["lines"]) * (v["size"] + 12) + 16 for v in layouts) - 16
        if height > 340:
            raise ValueError("No-image point exceeds its compact reading panel")
        y = (rect[1] + rect[3] - height) / 2
        for layout in layouts:
            for text in layout["lines"]:
                tile = native.ink(
                    text, cfg["fonts"]["title"], layout["size"], (65, 45, 25, 255)
                )
                words.alpha_composite(
                    tile, (round((rect[0] + rect[2] - tile.width) / 2), round(y))
                )
                y += layout["size"] + 12
            y += 16
        enter = native.out(scene["entry"][0] - 1, scene["entry"][1], n)
        leave = 1 - native.ease(scene["exit"][0] - 1, scene["exit"][1], n)
        for key, layer in (("info_plate", plate), ("info_text", words)):
            roles[f"{key}_{i}"] = native.opacity(
                native.pixel_phase(layer, rect, enter), leave
            )
        metrics.append({"phase": i, "rect": rect, "text_without_image": True})
    return roles, metrics


@contextmanager
def execution(module: Any, payload: dict) -> Iterator[None]:
    """Scoped hooks only in the isolated renderer; restore on every exit."""
    cfg = payload["config"]
    policy = cfg.get("conditional_layout")
    if not policy:
        yield
        return
    if policy.get("version") != VERSION or policy.get("sha256") != identity()["sha256"]:
        raise ValueError("Conditional display policy differs from compiled input")
    template = payload["template_id"]
    patches = []

    def replace(target: Any, name: str, value: Any) -> None:
        patches.append((target, name, vars(target)[name]))
        vars(target)[name] = value

    try:
        if template == "bihuo-03-v1":
            replace(
                module.top, "step_nodes", lambda c, t, s: _steps(module.top, c, t, s)
            )
        elif template == "bihuo-08-v1":
            old = module.E.material_layers
            replace(
                module.E,
                "material_layers",
                lambda c, n, out: _photo_text(module.E, old, c, n, out),
            )
        elif template == "bihuo-09-v1" and not cfg["materials"]:
            engine = module.E
            replace(engine, "materials", lambda c, n: _text_panels(engine, c, n))

            def text_pose(c: dict, n: int) -> tuple:
                normal = [102, 508, 894, 868]
                target = [64, 620, 440, 440]
                q = max(
                    [0.0] + [engine.phase(c, i, n) for i in range(len(c["phases"]))]
                )
                rect = [
                    a * (1 - q) + b * q for a, b in zip(normal, target, strict=True)
                ]
                return rect, 20 + 200 * q, q

            replace(engine, "pose", text_pose)
            old_caps = engine.captions

            def paper_captions(c: dict, n: int) -> tuple:
                layers, meta = old_caps(c, n)
                ink = Image.new("RGBA", engine.SIZE, (65, 45, 25, 0))
                ink.putalpha(layers["caption"].getchannel("A"))
                layers["caption"] = ink
                return layers, meta

            replace(engine, "captions", paper_captions)
        elif template == "bihuo-13-v1" and (
            cfg["title"].strip() or cfg["support"].strip()
        ):
            old_rect = module.E.person_rect

            def opening_rect(c: dict, n: int) -> list:
                rect = old_rect(c, n)
                _, f = c["title_events"]["exit"]
                q = 1 - module.E.ease(f, f + 12, n)
                shift = (
                    max(0, c["conditional_layout"]["opening_presenter_top"] - rect[1])
                    * q
                )
                return [rect[0], rect[1] + shift, rect[2], rect[3] - shift]

            replace(module.E, "person_rect", opening_rect)
        yield
    finally:
        for target, name, value in reversed(patches):
            vars(target)[name] = value
