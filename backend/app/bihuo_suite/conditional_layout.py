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
TARGETS = {
    "bihuo-03-v1",
    "bihuo-04-v1",
    "bihuo-08-v1",
    "bihuo-09-v1",
    "bihuo-13-v1",
    "bihuo-14-v1",
    "bihuo-16-v1",
    "bihuo-19-v1",
    "bihuo-40-v1",
}


def identity() -> dict:
    from . import adaptive_layout

    return {
        "version": VERSION,
        "sha256": hashlib.sha256(
            Path(__file__).read_bytes() + Path(adaptive_layout.__file__).read_bytes()
        ).hexdigest(),
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
    elif template == "bihuo-09-v1":
        phases = cfg["phases"]
        quote = cfg["resolved_plan"].get("quote_start")
        closing = round(quote * 25) if quote is not None else cfg["fade_start"]
        for phase in phases:
            original = copy.deepcopy(phase)
            phase["spoken_display_events"] = original
            # Move the person before a card arrives, including text-only spans
            # inside a mixed-material plan. Never reorder semantic slot indices.
            phase["person_entry"] = [phase["entry"][0] - 14, phase["entry"][0] - 2]
            if phase.get("asset_id"):
                continue
            next_start = min(
                (p["entry"][0] for p in phases if p["entry"][0] > phase["entry"][0]),
                default=closing,
            )
            end = max(phase["exit"][0], next_start)
            phase["exit"] = [end, min(cfg["frame_count"] - 1, end + 9)]
            phase["background_exit"] = [end, min(cfg["frame_count"] - 1, end + 11)]
        policy["hold_points_between_spoken_spans"] = True
        policy["paper_composition"] = "content-led/2"
        policy["paper_caption_layouts"] = {
            row["id"]: _paper_caption_layout(row, cfg["fonts"]["body"])
            for row in cfg.get("captions", [])
        }
    elif template == "bihuo-13-v1":
        policy["opening_presenter_top"] = 380 if cfg["support"].strip() else 276
    from . import adaptive_layout

    adaptive_layout.prepare(template, cfg, policy)
    cfg["conditional_layout"] = policy
    return {**payload, "config": cfg}


def _paper_labels(
    texts: list[str], font: str, width: int, sizes: tuple, rows: int, height: int
) -> list[dict]:
    for size in sizes:
        try:
            layouts = [_label(text, font, width, (size,), rows) for text in texts]
        except ValueError:
            continue
        total = sum(len(v["lines"]) * (v["size"] + 12) + 16 for v in layouts) - 16
        if total <= height:
            return layouts
    raise ValueError("Paper labels exceed their separate reading area")


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


def _text_panels(
    native: Any, cfg: dict, n: int, indices: set[int] | None = None
) -> tuple[dict, list]:
    roles = {}
    metrics = []
    for i, scene in enumerate(cfg["phases"]):
        if indices is not None and i not in indices:
            continue
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
        layouts = _paper_labels(
            texts, cfg["fonts"]["title"], 432, (64, 58, 52, 46, 40, 34), 3, 340
        )
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


def _material_headers(native: Any, original: Any, cfg: dict, n: int) -> tuple:
    # Reuse the native blurred backdrops, without painting an ordinal-specific
    # foreground that will immediately be replaced. The saved input is intact.
    phases = [
        {
            **phase,
            "note_title": "",
            "note_detail": "",
            "example": "",
            "entry": [
                cfg.get("frame_count", 100000) + 1,
                cfg.get("frame_count", 100000) + 2,
            ],
        }
        for phase in cfg["phases"]
    ]
    active = set()
    for i, phase in enumerate(cfg["phases"]):
        background = native.out(
            phase["background_entry"][0] - 1, phase["background_entry"][1], n
        ) * (
            1
            - native.ease(
                phase["background_exit"][0] - 1, phase["background_exit"][1], n
            )
        )
        if background > 0 or native.phase(cfg, i, n) > 0:
            active.add(i)
    # Zero-alpha media still triggered a full-screen resize/blur in the frozen
    # painter. Excluding it here preserves the pixels and the source clocks.
    visible = [
        material
        for material in cfg["materials"]
        if material["semantic_segment"] in active
    ]
    # Native still-image caches use paths as keys. Prepared video frame paths
    # change every frame; retain only the currently bound images, not a whole
    # clip's decoded RGBA frames. Static uploaded images keep their old cache.
    streams = cfg.get("video_materials", {}).get("streams", [])
    if streams:
        from pathlib import Path

        folders = {str(Path(stream["frames"][0]["path"]).parent) for stream in streams}
        current = {material["path"] for material in cfg["materials"]}
        cache = native.M._IMAGES
        for path in list(cache):
            if str(Path(path).parent) in folders and path not in current:
                cache.pop(path)
    roles, _ = original({**cfg, "phases": phases, "materials": visible}, n)
    metrics = []
    text_indices = set()
    foreground = [i for i in active if native.phase(cfg, i, n) > 0]
    heading = max(foreground, key=lambda i: cfg["phases"][i]["entry"][0], default=-1)
    if heading >= 0:
        for j, upcoming in enumerate(cfg["phases"]):
            if (
                cfg["phases"][heading]["entry"][0] < upcoming["entry"][0]
                and upcoming["person_entry"][0] <= n < upcoming["entry"][0]
                and bool(native.asset(cfg, heading)) != bool(native.asset(cfg, j))
            ):
                heading = -1
                break
    for i, phase in enumerate(cfg["phases"]):
        if native.phase(cfg, i, n) <= 0:
            continue
        material = native.asset(cfg, i)
        if not material:
            text_indices.add(i)
            continue
        with Image.open(material["path"]) as image:
            scale = min(972 / image.width, 960 / image.height)
            w, h = image.width * scale, image.height * scale
        rect = [
            round((1080 - w) / 2),
            round((1740 - h) / 2),
            round((1080 + w) / 2),
            round((1740 + h) / 2),
        ]
        plate_rect = [rect[0] - 12, rect[1] - 12, rect[2] + 12, rect[3] + 12]
        plate = native.blank()
        ImageDraw.Draw(plate).rounded_rectangle(
            tuple(plate_rect), radius=28, fill=(244, 233, 213, 255)
        )
        photo = native.media_layer(material["path"], rect, 18, "contain")
        enter = native.out(phase["entry"][0] - 1, phase["entry"][1], n)
        leave = 1 - native.ease(phase["exit"][0] - 1, phase["exit"][1], n)
        roles[f"info_plate_{i}"] = native.opacity(
            native.pixel_phase(plate, plate_rect, enter), leave
        )
        roles[f"material_{i}"] = native.opacity(
            native.pixel_phase(photo, rect, enter), leave
        )
        roles[f"info_text_{i}"] = (
            native.opacity(_paper_heading(native, cfg, phase), native.phase(cfg, i, n))
            if i == heading
            else native.blank()
        )
        metrics.append(
            {
                "phase": i,
                "actual_asset_id": material["id"],
                "rect": rect,
                "header_rect": [54, 96, 702, 350],
                "fit": "contain",
                "content_led": True,
            }
        )
    text_roles, text_metrics = _text_panels(native, cfg, n, text_indices)
    for i in text_indices:
        if i != heading:
            text_roles[f"info_text_{i}"] = native.blank()
    roles.update(text_roles)
    metrics.extend(text_metrics)
    return roles, metrics


def _paper_heading(native: Any, cfg: dict, phase: dict) -> Image.Image:
    rect = [54, 96, 702, 350]
    texts = [
        t.strip() for t in (phase["note_title"], phase["note_detail"]) if t.strip()
    ]
    layouts = _paper_labels(
        texts, cfg["fonts"]["title"], 600, (44, 40, 36, 32, 28), 2, 230
    )
    height = sum(len(v["lines"]) * (v["size"] + 8) + 8 for v in layouts) - 8
    layer = native.blank()
    if not texts:
        return layer
    ImageDraw.Draw(layer).rounded_rectangle(
        tuple(rect), radius=22, fill=(244, 233, 213, 244)
    )
    y = (rect[1] + rect[3] - height) / 2
    for layout in layouts:
        for line in layout["lines"]:
            tile = native.ink(
                line, cfg["fonts"]["title"], layout["size"], (65, 45, 25, 255)
            )
            layer.alpha_composite(
                tile, (round((rect[0] + rect[2] - tile.width) / 2), round(y))
            )
            y += layout["size"] + 8
        y += 8
    return layer


def _paper_caption_layout(row: dict, font: str) -> dict:
    layout = _label(row["text"], font, 920, (80, 76, 72, 68, 64, 60, 58), 2)
    cursor = 0
    breaks = []
    for line in layout["lines"][:-1]:
        cursor += len(line)
        breaks.append(cursor)
    if any(a < cut < b for a, b in row.get("emphasis_spans", []) for cut in breaks):
        return {"size": 58, "line_breaks": row.get("line_breaks", [])}
    return {"size": layout["size"], "line_breaks": breaks}


def _paper_pose(native: Any, cfg: dict, n: int) -> tuple:
    rect = [102.0, 508.0, 894.0, 868.0]
    radius, weight = 20.0, 0.0
    for i, phase in enumerate(cfg["phases"]):
        if not native.meaningful(cfg, i):
            continue
        start, end = phase["person_entry"]
        leave = phase["background_exit"][1]
        q = native.out(start, end, n) * (1 - native.ease(leave + 1, leave + 19, n))
        if q <= 0:
            continue
        target, corner = (
            ([748, 70, 280, 280], 140)
            if native.asset(cfg, i)
            else ([64, 620, 440, 440], 220)
        )
        rect = [a * (1 - q) + b * q for a, b in zip(rect, target, strict=True)]
        radius = radius * (1 - q) + corner * q
        weight = max(weight, q)
    return rect, radius, weight


def _paper_captions(native: Any, cfg: dict, n: int) -> tuple:
    local = dict(cfg)
    local["caption_baseline"] = cfg["caption_baseline"]
    row = next((r for r in cfg["captions"] if r["range"][0] <= n < r["range"][1]), None)
    if row:
        layout = cfg["conditional_layout"]["paper_caption_layouts"][row["id"]]
        local["body_size"] = layout["size"]
        local["captions"] = [{**row, "line_breaks": layout["line_breaks"]}]
    layers, meta = native._old_captions(local, n)
    ink = Image.new("RGBA", native.SIZE, (65, 45, 25, 0))
    ink.putalpha(layers["caption"].getchannel("A"))
    plate = native.blank()
    if bounds := ink.getbbox():
        x, y, x2, y2 = bounds
        ImageDraw.Draw(plate).rounded_rectangle(
            (max(20, x - 22), max(0, y - 14), min(1060, x2 + 22), min(1920, y2 + 14)),
            radius=18,
            fill=(249, 241, 226, 235),
        )
    return {"caption_shadow": plate, "caption": ink}, meta


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
        elif template == "bihuo-09-v1":
            engine = module.E
            old_materials = engine.materials
            replace(
                engine,
                "materials",
                lambda c, n: _material_headers(engine, old_materials, c, n),
            )
            replace(engine, "pose", lambda c, n: _paper_pose(engine, c, n))
            replace(engine, "captions", lambda c, n: _paper_captions(engine, c, n))
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
        from . import adaptive_layout

        with adaptive_layout.execution(module, payload):
            yield
    finally:
        for target, name, value in reversed(patches):
            vars(target)[name] = value
