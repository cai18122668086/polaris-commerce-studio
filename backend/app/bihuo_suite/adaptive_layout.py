"""Content-sized reading areas around unchanged native palettes and motion helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


def fit(
    text: str,
    font: str,
    width: float,
    sizes: tuple = (44, 40, 36, 32, 28),
    rows: int = 3,
) -> dict:
    from .conditional_layout import _label

    return _label(text, font, width, sizes, rows)


@lru_cache(maxsize=48)
def dimensions(path: str, kind: str = "image") -> tuple[int, int]:
    if kind == "video":
        import cv2

        cap = cv2.VideoCapture(path)
        try:
            return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(
                cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            )
        finally:
            cap.release()
    with Image.open(path) as im:
        return im.size


def prepare(template: str, cfg: dict, policy: dict) -> None:
    if template in {"bihuo-03-v1", "bihuo-04-v1"}:
        policy["application_materials"] = "content-led/1"
    if template == "bihuo-14-v1":
        policy["teal_materials"] = "content-led/1"
    if template in {"bihuo-16-v1", "bihuo-19-v1", "bihuo-40-v1"}:
        policy["reading_cards"] = "content-led/1"


def app_geometry(material: dict, bottom: bool) -> tuple[list[int], list[int]]:
    w, h = dimensions(material["path"], material.get("type", "image"))
    portrait = h > w * 1.1
    if portrait:
        return (
            [520, 430 if bottom else 850, 936, 970 if bottom else 1390],
            [148, 460 if bottom else 910, 476, 900 if bottom else 1340],
        )
    return (
        [144, 560 if bottom else 970, 936, 985 if bottom else 1395],
        [148, 410 if bottom else 835, 930, 535 if bottom else 950],
    )


def scene_texts(cfg: dict, t: float, native: Any) -> list[tuple[str, tuple]]:
    scene, _ = native.scene_at(cfg, t)
    if not scene:
        return []
    items = [v for v in scene.get("items", []) if v["at"] <= t]
    if items:
        return [(items[-1]["text"], native.BLUE)]
    contrasts = [
        v
        for v in scene.get("contrast", [])
        if float(v.get("at", (v.get("phase") or [0])[0])) <= t
    ]
    if contrasts:
        return [
            (v["text"], native.BLUE if v.get("emphasis") else native.BLACK)
            for v in contrasts
            if v.get("text")
        ]
    quote = scene.get("quote") or {}
    if quote:
        return [
            (quote[k], native.BLUE if k == "second" else native.BLACK)
            for k in ["first", "second"]
            if quote.get(k) and t >= quote.get(k + "_at", scene["at"])
        ]
    return [
        (scene[k], native.BLUE if k == "blue" else native.BLACK)
        for k in ["gray", "blue"]
        if scene.get(k)
    ]


def app_information(native: Any, cfg: dict, t: float, bottom: bool) -> Image.Image:
    layer = native.blank(cfg)
    m = native.material_at(cfg, t)
    if not m:
        return layer
    _, area = app_geometry(m, bottom)
    x, y, x2, y2 = area
    texts = scene_texts(cfg, t, native)
    if not texts:
        texts = [(m.get("label", ""), native.BLUE)]
    from .conditional_layout import _paper_labels

    layouts = _paper_labels(
        [text for text, _ in texts],
        cfg["fonts"]["bold"],
        x2 - x,
        (40, 36, 32, 28, 24),
        4 if x2 - x < 400 else 2,
        y2 - y,
    )
    for (text, color), display in zip(texts, layouts, strict=True):
        if not text:
            continue
        for line in display["lines"]:
            native.put(layer, cfg, line, display["size"], x, y, color, max_width=x2 - x)
            y += display["size"] + 12
    return layer


def app_material(native: Any, cfg: dict, t: float, bottom: bool) -> Image.Image:
    layer = native.blank(cfg)
    m = native.material_at(cfg, t)
    if not m:
        return layer
    box, _ = app_geometry(m, bottom)
    row = dict(
        id=m["id"],
        path=m["path"],
        type=m.get("type", "image"),
        start_frame=round(m["start"] * 25),
        rect=[v / 2 for v in box],
        fit="contain",
        anchor=[0.5, 0.5],
        radius=10,
        entry_frames=8,
        entry_blur=4,
        source_in=0,
        speed=1,
        end_policy="hold",
        audio="muted",
    )
    for image in native.approved_media.render(
        "V03", None, round(t * 25), dict(size=cfg["size"], fps=25, media_entries=[row])
    ).values():
        layer.alpha_composite(image)
    return native.fade(layer, 1 - native.ease(m["end"] - 0.16, m["end"], t))


@lru_cache(maxsize=96)
def compact_textcard(text: str, path: str, w: int, h: int) -> Image.Image:
    for size in (88, 80, 72, 64, 56, 48, 40, 32, 28):
        try:
            display = fit(
                text, path, w - 72, (size,), max(1, min(6, (h - 64) // (size + 14)))
            )
            break
        except ValueError:
            continue
    else:
        raise ValueError("Information text exceeds its actual reading area")
    size = display["size"]
    lineheight = size + 14
    plateheight = min(h - 8, len(display["lines"]) * lineheight + 56)
    top = 36 if h > 650 else max(4, (h - plateheight) // 2)
    im = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(im)
    face = ImageFont.truetype(path, size)
    width = min(w - 8, max(260, max(face.getlength(v) for v in display["lines"]) + 72))
    left = (w - width) / 2
    d.rounded_rectangle(
        (left, top, left + width, top + plateheight), radius=24, fill=(30, 38, 46, 244)
    )
    y = top + 28
    for line in display["lines"]:
        d.text((w / 2, y), line, font=face, fill="white", anchor="mt")
        y += lineheight
    return im


@lru_cache(maxsize=16)
def contained(path: str, w: int, h: int) -> Image.Image:
    with Image.open(path) as image:
        im = ImageOps.contain(image.convert("RGBA"), (w, h), Image.Resampling.LANCZOS)
    return im


def transparent_window(
    original: Callable, texture: Image.Image, box: list | tuple, radius: float
) -> Image.Image:
    """Keep unused reading-card padding transparent through native video windows."""
    if "A" not in texture.getbands() or texture.getchannel("A").getextrema()[0] == 255:
        return original(texture, box, radius)
    from PIL import ImageChops

    x, y, x2, y2 = map(round, box)
    tile = texture.resize((max(1, x2 - x), max(1, y2 - y)), Image.Resampling.BICUBIC)
    mask = Image.new("L", tile.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, tile.width - 1, tile.height - 1), radius=radius, fill=255
    )
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))
    result = Image.new("RGBA", (1080, 1920))
    result.alpha_composite(tile, (x, y))
    return result


def milkblue_caption(
    native: Any, original: Callable, c: dict, n: int, out: dict
) -> None:
    row = next(
        (v for v in c["captions"] if v["time"][0] <= n / 25 < v["time"][1]), None
    )
    if not row or native.font(c["font"], 76).getlength(row["text"]) <= 1000:
        original(c, n, out)
        return
    from PIL import ImageFilter

    display = fit(row["text"], c["font"], 1000, (76, 72, 68, 64, 60), 2)
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in row.get("lines", []):
        spans.extend(
            (a + offset, b + offset) for a, b in line.get("emphasis_spans", [])
        )
        offset += len(line["text"])
    size = display["size"]
    face = native.font(c["font"], size)
    ref = face.getbbox("国", anchor="ls", stroke_width=2)
    offset = 0
    for j, line in enumerate(display["lines"]):
        top = 1598 - (len(display["lines"]) - 1) * 112 + j * 112
        x = (1080 - sum(face.getlength(ch) for ch in line)) / 2
        for ch in line:
            mark = any(a <= offset < b for a, b in spans)
            tile, bounds, pad = native.glyph(ch, c["font"], size, mark)
            baseline = top - ref[1] - (10 if mark else 0)
            out["caption_emphasis" if mark else "caption_body"].alpha_composite(
                tile, (round(x + bounds[0] - pad), round(baseline + bounds[1] - pad))
            )
            x += face.getlength(ch)
            offset += 1
    q = min(1, (n / 25 - row["time"][0] + 0.04) / 0.28)
    for key in ["caption_body", "caption_emphasis"]:
        out[key] = native.opacity(out[key], q)
    alpha = Image.alpha_composite(
        out["caption_body"], out["caption_emphasis"]
    ).getchannel("A")
    shadow = native.blank()
    shadow.putalpha(
        alpha.filter(ImageFilter.GaussianBlur(2)).point(lambda a: round(a * 0.8))
    )
    out["caption_shadow"].alpha_composite(shadow, (3, 4))


def milkblue_render(
    native: Any,
    original: Callable,
    raw: Image.Image,
    c: dict,
    n: int,
    roles: bool = False,
) -> Any:
    _, out = original(raw, c, n, roles=True)
    t = n / 25
    active = [m for m in c["materials"] if m["start"] <= t < m["end"] + 0.28]
    text = out["material_text"].getbbox()
    if active or (text and out["presenter_foreground"].getbbox()):
        for k in ["outline_cyan", "outline_white", "presenter_foreground"]:
            out[k] = native.blank()
        native.subject(raw, c, n, [390, 80, 690, 490], out)
        if active:
            current = active[-1]
            q = native.ramp(t, current["start"], current["start"] + 0.52) * (
                1 - native.ramp(t, current["end"], current["end"] + 0.28)
            )
            layer = native.blank()
            tile = contained(current["path"], 972, 900)
            x = (1080 - tile.width) // 2
            y = 540 + (900 - tile.height) // 2
            ImageDraw.Draw(layer).rounded_rectangle(
                (x - 10, y - 10, x + tile.width + 10, y + tile.height + 10),
                radius=22,
                fill=(244, 247, 250, 255),
            )
            layer.alpha_composite(tile, (x, y))
            index = c["materials"].index(current)
            if index:
                previous = contained(c["materials"][index - 1]["path"], 260, 260)
                layer.alpha_composite(previous, (54, 130))
            out["materials"] = native.opacity(layer, q)
        elif text:
            tile = out["material_text"].crop(text)
            tile.thumbnail((940, 650), Image.Resampling.LANCZOS)
            out["material_text"] = native.blank()
            out["material_text"].alpha_composite(tile, ((1080 - tile.width) // 2, 650))
    result = Image.new("RGBA", (1080, 1920), (0, 0, 0, 255))
    for layer in out.values():
        result.alpha_composite(layer)
    if t > c["duration"] - 0.52:
        result = Image.blend(
            Image.new("RGBA", result.size, (0, 0, 0, 255)),
            result,
            1 - native.ramp(t, c["duration"] - 0.52, c["duration"] - 0.04),
        )
    return (result.convert("RGB"), out) if roles else result.convert("RGB")


def coherent_head(native: Any, raw: Image.Image, c: dict, n: int, out: dict) -> None:
    """Use one source transform for the circle and its existing head breakout."""
    alpha = native.alpha_image(c["foreground_alpha"][str(n)]["path"])
    bounds = alpha.getbbox()
    if not bounds:
        return
    first = (
        native.alpha_image(next(iter(c["foreground_alpha"].values()))["path"]).getbbox()
        or bounds
    )
    scale = 270 / max(1, first[2] - first[0])
    x = round(540 - (first[0] + first[2]) / 2 * scale)
    y = round(141 - first[1] * scale)
    size = (round(raw.width * scale), round(raw.height * scale))
    native.glowing_window(raw, [405, 236, 675, 506], 135, out)
    room = native.blank()
    room.alpha_composite(
        raw.convert("RGBA").resize(size, Image.Resampling.LANCZOS), (x, y)
    )
    mask = Image.new("L", (1080, 1920))
    ImageDraw.Draw(mask).ellipse((405, 236, 675, 506), fill=255)
    room.putalpha(mask)
    out["presenter_room"] = room
    foreground = raw.copy()
    foreground.putalpha(alpha)
    layer = native.blank()
    layer.alpha_composite(foreground.resize(size, Image.Resampling.LANCZOS), (x, y))
    layer.paste((0, 0, 0, 0), (0, 506, 1080, 1920))
    out["head_foreground"] = layer


def teal_parts(
    B: Any, c: dict, t: float, info: dict, matched: dict | None, second: bool = False
) -> tuple | None:
    empty = tuple(B.blank() for _ in range(4))
    if not matched:
        return None
    q = B.ease(info["start"] - 0.28, info["start"], t) * (
        1 - B.ease(info["end"], info.get("clear", info["end"] + 0.32), t)
    )
    q *= B.ease(matched["start"] - 0.04, matched["start"] + 0.28, t) * (
        1 - B.ease(matched["end"] - 0.16, matched["end"], t)
    )
    if q <= 0:
        return empty
    cards, media, labels, items = empty
    w, h = dimensions(matched["path"])
    portrait = h > w * 1.1
    ImageDraw.Draw(cards).rounded_rectangle(
        (72, 270, 1008, 1025), radius=42, fill="white"
    )
    label = fit(info.get("label", ""), c["fonts"]["bold"], 800, (30, 28, 26), 2)
    y = 298
    for line in label["lines"]:
        B.put(
            labels, line, c["fonts"]["bold"], label["size"], 134, y, (0, 112, 87, 255)
        )
        y += label["size"] + 8
    rows = info.get("items", [])
    width = 310 if portrait else 790
    displays = [
        fit(
            row["text"],
            c["fonts"]["bold"],
            width,
            (34, 32, 30, 28),
            3 if portrait else 2,
        )
        for row in rows
    ]
    total = sum(len(d["lines"]) * (d["size"] + 9) + 14 for d in displays)
    box = (
        [114, 410, 530, 990]
        if portrait
        else [114, y + 24, 966, max(y + 120, 990 - total - 20)]
    )
    media = B.image_slot(matched["path"], box, t, radius=22, fit="contain")
    y = 440 if portrait else 990 - total
    for row, display in zip(rows, displays, strict=True):
        tile = B.blank()
        yy = y
        for line in display["lines"]:
            B.put(
                tile,
                line,
                c["fonts"]["bold"],
                display["size"],
                578 if portrait else 148,
                yy,
                (5, 14, 11, 255),
            )
            yy += display["size"] + 9
        items.alpha_composite(B.fade(tile, B.ease(row["start"] - 0.04, row["near"], t)))
        y = yy + 14
    proxy = c
    phase = t
    if second:
        proxy = dict(c, mode="baseline")
        phase = (
            193 + (t - info["start"]) * 25
            if t < info.get("near", info["start"] + 0.2)
            else 248 + (t - info["end"]) * 25
            if t >= info["end"]
            else 220
        ) / 25
    return tuple(
        B.fade(B.card_motion(layer, phase, proxy), q)
        for layer in [cards, media, labels, items]
    )


@contextmanager
def execution(module: Any, payload: dict) -> Iterator[None]:
    tid = payload["template_id"]
    patches = []

    def patch(target: Any, name: str, value: Any) -> None:
        patches.append((target, name, vars(target)[name]))
        vars(target)[name] = value

    try:
        if tid in {"bihuo-03-v1", "bihuo-04-v1"}:
            bottom = tid == "bihuo-04-v1"
            native = module.bottom.BASE if bottom else module.top
            for name, helper in [
                ("body", app_information),
                ("materials", app_material),
            ]:
                old = getattr(native, name)

                def wrapped(
                    c: dict, t: float, old: Any = old, helper: Any = helper
                ) -> Image.Image:
                    return (
                        helper(native, c, t, bottom)
                        if native.material_at(c, t)
                        else old(c, t)
                    )

                patch(native, name, wrapped)
            if bottom:
                old_contrast = module.bottom.contrast
                old_support = module.bottom.quote_support
                patch(
                    module.bottom,
                    "contrast",
                    lambda c, t, s: (
                        {} if native.material_at(c, t) else old_contrast(c, t, s)
                    ),
                )
                patch(
                    module.bottom,
                    "quote_support",
                    lambda c, t: (
                        native.blank(c)
                        if native.material_at(c, t)
                        else old_support(c, t)
                    ),
                )
        elif tid in {"bihuo-16-v1", "bihuo-19-v1", "bihuo-40-v1"}:
            namespace = module.encode.__globals__
            native = __import__(namespace["__name__"], fromlist=["textcard"])
            patch(native, "textcard", compact_textcard)
            old_window = native.window
            patch(
                native,
                "window",
                lambda texture, box, radius: transparent_window(
                    old_window, texture, box, radius
                ),
            )
            if tid == "bihuo-16-v1":
                old_caption = native.caption
                patch(
                    native,
                    "caption",
                    lambda c, n, out: milkblue_caption(native, old_caption, c, n, out),
                )
                old = native.render
                patch(
                    native,
                    "render",
                    lambda raw, c, n, roles=False: milkblue_render(
                        native, old, raw, c, n, roles
                    ),
                )
            elif tid == "bihuo-19-v1":
                patch(
                    native,
                    "head",
                    lambda raw, c, n, out: coherent_head(native, raw, c, n, out),
                )
        elif tid == "bihuo-14-v1":
            B = module.E.B
            old = B.materials
            old2 = module.E.card2

            def first(c: dict, t: float) -> tuple:
                result = old(c, t)
                m = next(
                    (
                        m
                        for m in c["materials"]
                        if m.get("scene_role") == "first-card"
                        and m["start"] <= t < m["end"]
                    ),
                    None,
                )
                parts = teal_parts(B, c, t, c["information"], m)
                return parts if parts is not None else result

            def second(c: dict, t: float) -> tuple:
                m = next(
                    (
                        m
                        for m in c["materials"]
                        if m.get("scene_role") == "second-card"
                        and m["start"] <= t < m["end"]
                    ),
                    None,
                )
                parts = teal_parts(B, c, t, c["second_information"], m, True)
                return parts if parts is not None else old2(c, t)

            patch(B, "materials", first)
            patch(module.E, "card2", second)
        yield
    finally:
        for target, name, old in reversed(patches):
            vars(target)[name] = old
