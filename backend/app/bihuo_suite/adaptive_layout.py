"""Content-sized reading areas around unchanged native palettes and motion helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


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
    if template == "bihuo-10-v1":
        policy["paper_card_fit"] = "content-lines/1"
    if template == "bihuo-36-v1":
        policy["silver_caption_fit"] = "bounded-native-fonts/1"
    if template in {"bihuo-03-v1", "bihuo-04-v1"}:
        policy["application_materials"] = "content-led/1"
    if template == "bihuo-14-v1":
        policy["teal_materials"] = "content-led/1"
    if template in {"bihuo-16-v1", "bihuo-19-v1", "bihuo-40-v1"}:
        policy["reading_cards"] = "content-led/1"
    if template == "bihuo-47-v1":
        policy["business_caption_fit"] = "balanced-overflow-cut/1"


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


SILVER_MAX_WIDTH = 1030
_BREAK_AFTER = "，。、；：！？,.;:!? "


def split_caption_line(
    line: dict, pieces: int, prefer_punctuation: bool = True
) -> list[dict] | None:
    """Split one caption line into ``pieces`` lines without changing a word.

    Cuts land near equal lengths, prefer the place right after punctuation and
    never fall inside an emphasis span; each span moves to its own line with
    its offsets re-based. None when no such cut exists.
    """
    text = line["text"]
    spans = [list(span) for span in line.get("emphasis_spans", [])]
    cuts: list[int] = []
    for k in range(1, pieces):
        target = len(text) * k / pieces
        best: tuple[float, int] | None = None
        for pos in range(1, len(text)):
            if (cuts and pos <= cuts[-1]) or any(a < pos < b for a, b in spans):
                continue
            after_mark = prefer_punctuation and text[pos - 1] in _BREAK_AFTER
            score = abs(pos - target) - (len(text) / pieces / 2 if after_mark else 0)
            if best is None or score < best[0]:
                best = (score, pos)
        if best is None:
            return None
        cuts.append(best[1])
    bounds = [0, *cuts, len(text)]
    return [
        {
            **line,
            "text": text[a:b],
            "emphasis_spans": [[x - a, y - a] for x, y in spans if a <= x and y <= b],
        }
        for a, b in zip(bounds, bounds[1:], strict=False)
    ]


def silver_whole_line(native: Any, original: Any, cfg: dict, cue: dict) -> Any:
    lines = cue.get("lines") or [
        {"text": cue["text"], "emphasis_spans": cue.get("emphasis_spans", [])}
    ]

    def fitted(rows: list[dict]) -> dict | None:
        for reduction in range(7):
            local = dict(
                cfg,
                white_size=cfg["white_size"] - reduction,
                gold_size=cfg["gold_size"] - reduction,
            )
            widths = [
                sum(
                    native.font(
                        cfg["fonts"]["caption"],
                        local["gold_size"] if active else local["white_size"],
                    ).getlength(text)
                    for text, active in native.visual.caption_parts({**cue, **row})
                )
                for row in rows
            ]
            if max(widths, default=0) <= SILVER_MAX_WIDTH:
                return local
        return None

    local = fitted(lines)
    if local is not None:
        return original(local, cue)
    # A sentence too long for one line even at the smallest size (long script
    # lines such as 「所以挑家具这件事，得先把标准想清楚」) used to fail the
    # native single-line gate and the whole render. The engine lays out two
    # (or three) lines itself; the words, clocks and emphasis stay the same.
    if len(lines) == 1:
        for pieces in (2, 3):
            for prefer in (True, False):
                rows = split_caption_line(lines[0], pieces, prefer)
                local = fitted(rows) if rows else None
                if rows and local is not None:
                    return original(local, {**cue, "lines": rows})
    return original(cfg, cue)  # Truly overlong content still fails the native gate.


# Native single-line caption gates of other installed suites, measured exactly
# like each bundle measures itself (bundle files stay byte-identical):
#   bihuo-23 快讯直播 primitives.captions  asserts one line <= 1010 px (66/76 px,
#            0.12 shear) and fails the whole render; its runtime already stacks
#            ``lines`` (88 px apart), so long sentences become 2–3 lines.
#   bihuo-24 深青标题 runtime.compile_request shrinks every caption of the video
#            to fit its widest line (64 -> 48 px) and rejects past that; at most
#            two lines. Splitting only the wide line keeps the others at 64 px.
CAPTION_WRAP = {"bihuo-23-v1": (1010, 3), "bihuo-24-v1": (1040, 2)}


def navy_line_width(native: Any, font: str, line: dict) -> int:
    F = native.F
    pieces = 0
    width = 0
    for text, active in F.V.caption_parts(
        {"text": line["text"], "emphasis_spans": line.get("emphasis_spans", [])}
    ):
        im = F.tile(text, font, 76 if active else 66, (255, 255, 255, 255))
        ext = round(0.12 * im.height) + 2
        im = im.transform(
            (im.width + ext, im.height),
            Image.Transform.AFFINE,
            (1, 0.12, -ext, 0, 1, 0),
            Image.Resampling.BICUBIC,
        )
        box = im.getchannel("A").getbbox()
        width += (box[2] - box[0]) if box else im.width
        pieces += 1
    return width + max(0, pieces - 1)


def qingbai_line_width(native: Any, font: str, line: dict, size: int = 64) -> int:
    E = native.E
    return sum(
        E.text_run(
            text, font, size + 12 if active else size, (255, 255, 255, 255)
        ).width
        for text, active in E.V.caption_parts(
            {"text": line["text"], "emphasis_spans": line.get("emphasis_spans", [])}
        )
    )


def wrap_caption_lines(
    lines: list[dict], measure: Callable[[dict], float], limit: float, most: int
) -> list[dict]:
    """Split only the lines wider than ``limit``; words, spans and order unchanged."""
    result: list[dict] = []
    for index, line in enumerate(lines):
        room = most - len(result) - (len(lines) - index - 1)
        if measure(line) <= limit or room < 2:
            result.append(line)
            continue
        best = None
        for pieces in range(2, room + 1):
            for prefer in (True, False):
                rows = split_caption_line(line, pieces, prefer)
                if rows and all(r["text"].strip() for r in rows):
                    widest = max(measure(r) for r in rows)
                    if best is None or widest < best[0]:
                        best = (widest, rows)
                    if widest <= limit:
                        break
            if best and best[0] <= limit:
                break
        result.extend(best[1] if best else [line])
    return result


def wrap_resolved_captions(
    template_id: str, native: Any, resolved: dict, fonts: dict
) -> dict:
    limit, most = CAPTION_WRAP[template_id]
    if template_id == "bihuo-23-v1":
        font = native.core._style_fonts(fonts)["caption"]

        def measure(line: dict) -> float:
            return navy_line_width(native, font, line)
    else:
        font = str(fonts.get("body") or fonts.get("caption") or "")

        def measure(line: dict) -> float:
            return qingbai_line_width(native, font, line)

    captions = []
    changed = False
    for row in resolved.get("captions", []):
        lines = row.get("lines") or [
            {"text": row["text"], "emphasis_spans": row.get("emphasis_spans", [])}
        ]
        lines = [
            x if isinstance(x, dict) else {"text": x, "emphasis_spans": []}
            for x in lines
        ]
        wrapped = wrap_caption_lines(lines, measure, limit, most)
        if len(wrapped) != len(lines):
            changed = True
            row = {**row, "lines": wrapped}
        captions.append(row)
    return {**resolved, "captions": captions} if changed else resolved


BUSINESS_WIDTH = 1044


def _business_segments(text: str, ranges: list, start: int, end: int) -> list:
    segments = []
    k = start
    for a, b in ranges:
        a, b = max(a, start), min(b, end)
        if a >= b:
            continue
        if k < a:
            segments.append((text[k:a], False))
        segments.append((text[a:b], True))
        k = b
    if k < end:
        segments.append((text[k:end], False))
    return [(s, mark) for s, mark in segments if s]


def _business_lines(F: Any, cfg: dict, text: str, ranges: list, cuts: list, floor: int):
    """bihuo-47's own line loop: size carries over between lines, -2 px steps."""
    size = 84
    start = 0
    lines = []
    for end in cuts:
        segments = _business_segments(text, ranges, start, end)

        def tiles(size: int, segments: list = segments) -> list:
            return [
                (
                    F.tile(s, cfg, size, (235, 203, 103, 255) if mark else "white", 3),
                    mark,
                )
                for s, mark in segments
            ]

        row = tiles(size)
        while sum(v.width for v, _ in row) > BUSINESS_WIDTH and size > floor:
            size -= 2
            row = tiles(size)
        lines.append((row, size))
        start = end
    return lines


def business_caps(native: Any, original: Callable, cfg: dict, n: int) -> tuple:
    """bihuo-47 cuts a long caption at the emphasis end nearest the middle and
    shrinks to 42 px; a lopsided cut (emphasis near the start) left the second
    line wider than the frame, clipped at both edges. Only then the host lays
    the same words out at a balanced cut; every fitting caption is native."""
    F = native.F
    r = next((r for r in cfg["captions"] if r["frames"][0] <= n < r["frames"][1]), None)
    if not r:
        return original(cfg, n)
    text, ranges = r["text"], r["emphasis_spans"]
    if F.tile(text, cfg, 84, "white", 3).width <= BUSINESS_WIDTH:
        return original(cfg, n)
    target = len(text) // 2
    candidates = [b for a, b in ranges if 2 <= b < len(text) - 1]
    cut = min(candidates, key=lambda x: abs(x - target)) if candidates else target
    lines = _business_lines(F, cfg, text, ranges, [cut, len(text)], 42)
    if all(sum(v.width for v, _ in row) <= BUSINESS_WIDTH for row, _ in lines):
        return original(cfg, n)
    rows = split_caption_line(
        {"text": text, "emphasis_spans": [list(x) for x in ranges]}, 2
    ) or split_caption_line({"text": text, "emphasis_spans": []}, 2)
    cut = len(rows[0]["text"]) if rows else target
    lines = _business_lines(F, cfg, text, ranges, [cut, len(text)], 30)
    out = {k: F.blank() for k in ["caption_shadow", "caption_body", "caption_emphasis"]}
    y = 1508
    for row, size in lines:
        x = (1080 - sum(v.width for v, _ in row)) / 2
        for im, mark in row:
            out["caption_emphasis" if mark else "caption_body"].alpha_composite(
                im, (round(x), y)
            )
            shadow = Image.new("RGBA", im.size, (0, 0, 0, 255))
            shadow.putalpha(im.getchannel("A").point(lambda z: round(z * 0.8)))
            out["caption_shadow"].alpha_composite(
                shadow.filter(ImageFilter.GaussianBlur(2)), (round(x + 4), y + 6)
            )
            x += im.width
        y += size + 20
    q = min(1, max(0, (n - r["frames"][0] + 1) / 8))
    if r.get("slide_entry"):
        p = native.core.pilot.ease(r["frames"][0], r["frames"][0] + 14, n)
        dx = round(210 * (1 - p))
        for k, im in out.items():
            moved = F.blank()
            moved.alpha_composite(im, (dx, 0))
            mask = Image.new("L", (1080, 1920))
            ImageDraw.Draw(mask).rectangle(
                (r.get("clip_left", 30), 0, 1079, 1919), fill=255
            )
            moved.putalpha(ImageChops.multiply(moved.getchannel("A"), mask))
            out[k] = moved
    return {k: F.fade(v, q) for k, v in out.items()}, dict(
        text=text, frames=r["frames"], line_count=len(lines), host_balanced_cut=cut
    )


def paper_card_layers(native: Any, original: Any, t: float, cfg: dict) -> dict:
    card = cfg["card"]
    ink = native.C.ink
    item_width = 254 if len(card["items"]) == 3 else 430

    def fitted(text: str, path: str, size: int, fill: tuple) -> Image.Image:
        width = (
            item_width
            if any(row["text"] == text for row in card["items"])
            else 390
            if text == card.get("button")
            else 800
        )
        face = ink(text, path, size, fill)
        if face.width <= width:
            return face
        display = fit(text, path, width, tuple(range(size, max(23, size - 12), -2)), 2)
        lines = [ink(line, path, display["size"], fill) for line in display["lines"]]
        face = Image.new(
            "RGBA",
            (
                max(line.width for line in lines),
                sum(line.height for line in lines) + 8 * (len(lines) - 1),
            ),
        )
        y = 0
        for line in lines:
            face.alpha_composite(line, ((face.width - line.width) // 2, y))
            y += line.height + 8
        return face

    native.C.ink = fitted
    try:
        return original(t, cfg)
    finally:
        native.C.ink = ink


@contextmanager
def compilation(template_id: str) -> Iterator[None]:
    from .registry import runtime

    if template_id in CAPTION_WRAP:
        module = runtime(template_id)
        compiler = vars(module)["compile_request"]

        def wrapped(resolved: dict, *args: Any, fonts: dict, **kwargs: Any) -> Any:
            ready = wrap_resolved_captions(template_id, module, resolved, fonts)
            return compiler(ready, *args, fonts=fonts, **kwargs)

        vars(module)["compile_request"] = wrapped
        try:
            yield
        finally:
            vars(module)["compile_request"] = compiler
        return
    if template_id != "bihuo-36-v1":
        yield
        return
    native = runtime(template_id).E
    original = native.whole_line
    native.whole_line = lambda c, cue: silver_whole_line(native, original, c, cue)
    try:
        yield
    finally:
        native.whole_line = original


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


def app_quote_layers(
    native: Any, original: Any, cfg: dict, t: float, scene: dict
) -> dict:
    """Wrap long source-backed conclusions without shortening their words."""
    data = scene.get("quote") or {}
    scale = cfg["size"][0] / 1080
    fields = [
        (key, data.get(key, ""), size) for key, size in [("first", 50), ("second", 54)]
    ]
    if all(
        not text
        or native.font(cfg["fonts"]["bold"], size * scale).getlength(text)
        <= 700 * scale
        for _, text, size in fields
    ):
        return original(cfg, t, scene)
    # Reuse the original quote mark, opacity and blur clocks. Blank placeholders
    # prevent its single-line painter from seeing overlong display strings.
    placeholder = {**data, **{key: " " if text else "" for key, text, _ in fields}}
    roles = original(cfg, t, {**scene, "quote": placeholder})
    y = 656 if all(text for _, text, _ in fields) else 692
    for key, text, size in fields:
        if not text:
            continue
        display = fit(text, cfg["fonts"]["bold"], 700, (size, 46, 42, 38, 34), 2)
        layer = native.blank(cfg)
        color = native.BLUE if key == "second" else native.BLACK
        for line in display["lines"]:
            native.put(layer, cfg, line, display["size"], 224, y, color, max_width=700)
            y += display["size"] + 12
        y += 6
        at = data.get(key + "_at", scene["at"])
        opacity = native.ease(at, at + data.get(key + "_opacity", 0.20), t)
        clear_at = data.get(key + "_blur_at", at)
        clear = native.ease(clear_at, clear_at + data.get(key + "_reveal", 0.32), t)
        if cfg.get("source_warm_frame") and t == 0 and key == "first":
            opacity = clear = 1
        roles[key] = native.fade(layer, opacity, (1 - clear) * 7 * scale)
    return roles


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
                old_quote = native.quote_layers
                patch(
                    native,
                    "quote_layers",
                    lambda c, t, scene: app_quote_layers(
                        native, old_quote, c, t, scene
                    ),
                )
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
        elif tid == "bihuo-36-v1":
            native = module.E
            original = native.whole_line
            patch(
                native,
                "whole_line",
                lambda c, cue: silver_whole_line(native, original, c, cue),
            )
        elif tid == "bihuo-47-v1":
            original_caps = vars(module)["_caps"]
            patch(
                module,
                "_caps",
                lambda c, n: business_caps(module, original_caps, c, n),
            )
        elif tid == "bihuo-10-v1":
            original_card = module.C.card_layers
            patch(
                module.C,
                "card_layers",
                lambda t, c: paper_card_layers(module, original_card, t, c),
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
