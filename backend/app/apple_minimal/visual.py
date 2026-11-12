"""Shared V01/V02/T01/T05 runtime. Input clocks belong to the composition."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .pilot import Suite, blend, ease, font, place_center, text_image

type Lines = tuple[str, ...]
type FontPath = str | Path
type RGBA = tuple[int, int, int, int]
type Inputs = dict[str, Any]
type Layers = dict[str, Image.Image]
type CardLayout = tuple[bool, Lines, float, Lines, float]


def _blur_alpha(image: Image.Image, radius: float) -> Image.Image:
    return (
        image.convert("RGBa").filter(ImageFilter.GaussianBlur(radius)).convert("RGBA")
    )


def _place_alpha(
    layer: Image.Image,
    image: Image.Image,
    cx: float,
    top: float,
    opacity: float = 1,
    scale: float = 1,
    blur: float = 0,
) -> None:
    if opacity <= 0:
        return
    if scale != 1:
        image = (
            image.convert("RGBa")
            .resize(
                (
                    max(1, round(image.width * scale)),
                    max(1, round(image.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
            .convert("RGBA")
        )
    if blur > 0:
        image = _blur_alpha(image, blur)
    if opacity < 1:
        image = image.copy()
        image.putalpha(image.getchannel("A").point(lambda a: round(a * opacity)))
    layer.alpha_composite(image, (round(cx - image.width / 2), round(top)))


def _line_metrics(lines: Lines, path: FontPath, size: float) -> tuple[float, float]:
    face = font(path, size)
    boxes = [face.getbbox(line, anchor="ls") for line in lines]
    width = max((b[2] - b[0] for b in boxes), default=0)
    height = (
        max((b[3] - b[1] for b in boxes), default=0) + (len(lines) - 1) * size * 1.12
        if lines
        else 0
    )
    return width, height


def _wrap_lines(text: str, path: FontPath, size: float, width: float) -> Lines:
    face = font(path, size)
    lines = []
    current = ""
    for character in text:
        candidate = current + character
        b = face.getbbox(candidate, anchor="ls")
        if character == "\n":
            lines.append(current)
            current = ""
        elif current and b[2] - b[0] > width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


@lru_cache(maxsize=128)
def _fit_opening(
    text: str,
    path: FontPath,
    preferred: float,
    minimum: float,
    width: float,
    height: float,
) -> tuple[Lines, float]:
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("Opening text exceeds supported capacity")
    if not text:
        return (), preferred
    # Keep normal v4 words at their original size and coordinates.
    natural = _line_metrics((text,), path, preferred)
    if "\n" not in text and natural[0] + 32 <= width and natural[1] <= height:
        return (text,), preferred
    for point in range(round(preferred), round(minimum) - 1, -1):
        lines = _wrap_lines(text, path, point, width - 32)
        w, h = _line_metrics(lines, path, point)
        if w + 32 <= width and h <= height:
            return lines, float(point)
    raise ValueError(
        "Opening title or subtitle is too long for this template; shorten the text"
    )


@lru_cache(maxsize=128)
def _text_block(
    lines: Lines,
    path: FontPath,
    size: float,
    color: RGBA,
    gradient: bool = False,
) -> Image.Image:
    if not lines:
        return Image.new("RGBA", (1, 1))
    pieces = [text_image(line, path, size, color)[0] for line in lines]
    width = max(p.width for p in pieces)
    height = round(_line_metrics(lines, path, size)[1]) + 32
    image = Image.new("RGBA", (width, height))
    for i, piece in enumerate(pieces):
        image.alpha_composite(
            piece, (round((width - piece.width) / 2), round(i * size * 1.12))
        )
    if gradient:
        alpha = image.getchannel("A")
        colors = np.zeros((image.height, image.width, 4), np.uint8)
        a = np.array([13, 77, 118])
        b = np.array([73, 73, 76])
        q = np.linspace(0, 1, image.width)[None, :, None]
        colors[:, :, :3] = (a[None, None, :] * (1 - q) + b[None, None, :] * q).astype(
            np.uint8
        )
        colors[:, :, 3] = np.asarray(alpha)
        image = Image.fromarray(colors)
    return image


@lru_cache(maxsize=128)
def _fit_name_card(
    name: str,
    description: str,
    name_font: FontPath,
    body_font: FontPath,
    k: float,
) -> CardLayout:
    if (
        not isinstance(name, str)
        or not isinstance(description, str)
        or len(name) > 32
        or len(description) > 80
    ):
        raise ValueError("Name card text exceeds supported capacity")
    width = 196 * k
    if (
        "\n" not in name + description
        and _line_metrics((name,), name_font, 22 * k)[0] <= width
        and _line_metrics((description,), body_font, 12 * k)[0] <= width
    ):
        return True, (name,), 22 * k, (description,) if description else (), 12 * k
    for name_size in range(round(22 * k), round(14 * k) - 1, -1):
        names = _wrap_lines(name, name_font, name_size, width)
        nw, nh = _line_metrics(names, name_font, name_size)
        for body_size in range(round(12 * k), round(10 * k) - 1, -1):
            descriptions = _wrap_lines(description, body_font, body_size, width)
            dw, dh = _line_metrics(descriptions, body_font, body_size)
            if (
                max(nw, dw) <= width
                and nh + dh + (4 * k if descriptions else 0) <= 56 * k
            ):
                return False, names, name_size, descriptions, body_size
    raise ValueError(
        "Name card is too long for the reserved area; shorten the name or description"
    )


def _draw_left_lines(
    layer: Image.Image,
    lines: Lines,
    path: FontPath,
    size: float,
    x: float,
    y: float,
    color: RGBA,
) -> None:
    for line in lines:
        image = text_image(line, path, size, color)[0]
        box = image.getchannel("A").getbbox()
        if box:
            layer.alpha_composite(image.crop(box), (round(x), round(y)))
        y += size * 1.12


class Typography(Suite):
    def __init__(self, inputs: Inputs) -> None:
        self.cfg = inputs
        self.W, self.H = inputs["size"]
        self.k = self.W / 540
        self.fonts = inputs["fonts"]
        self.static = {}


def interpolate(keys: list[Inputs], t: float) -> Inputs:
    if t <= keys[0]["time"]:
        return keys[0]
    for a, b in zip(keys, keys[1:], strict=False):
        if a["time"] <= t <= b["time"]:
            q = (t - a["time"]) / (b["time"] - a["time"])
            row: Inputs = {"time": t}
            for key in ["matrix", "rect", "radius", "background_opacity"]:
                x, y = a[key], b[key]
                row[key] = (
                    (np.array(x) * (1 - q) + np.array(y) * q).tolist()
                    if isinstance(x, list)
                    else blend(x, y, q)
                )
            return row
    return keys[-1]


def render(
    component_id: str,
    raw_frame: Image.Image,
    local_frame: int,
    inputs: Inputs,
    disabled: bool = False,
) -> Layers:
    if component_id not in {"V01", "V02"}:
        raise ValueError("Unknown visual component")
    W, H = inputs["size"]
    k = W / 540
    t = local_frame / inputs.get("fps", 25)

    def blank() -> Image.Image:
        return Image.new("RGBA", (W, H))

    background = Image.new(
        "RGBA",
        (W, H),
        cast(RGBA, tuple(inputs.get("stage_color", [254, 252, 255])) + (255,)),
    )
    person = blank()
    if disabled:
        return {"background": background, "presenter": person}
    pose = interpolate(inputs["visual_keys"], t)
    matrix = np.array(pose["matrix"], np.float32)
    matrix[:, 2] *= k
    raw = raw_frame.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")
    if pose["background_opacity"] > 0:
        bg = raw.filter(ImageFilter.GaussianBlur(16 * k)).convert("RGBA")
        bg.putalpha(round(255 * pose["background_opacity"]))
        background.alpha_composite(bg)
    pixels = cv2.warpAffine(
        np.array(raw),
        matrix,
        (W, H),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    person = Image.fromarray(pixels).convert("RGBA")
    alpha = Image.new("L", (W, H))
    r = cast(tuple[float, float, float, float], tuple(v * k for v in pose["rect"]))
    ImageDraw.Draw(alpha).rounded_rectangle(r, radius=pose["radius"] * k, fill=255)
    person.putalpha(alpha)
    return {"background": background, "presenter": person}


@lru_cache(maxsize=16)
def _type_helper(signature: str) -> Typography:
    import json

    return Typography(json.loads(signature))


def render_subtitle(
    component_id: str,
    local_frame: int,
    inputs: Inputs,
    disabled: bool = False,
) -> Layers:
    import json

    W, H = inputs["size"]
    k = W / 540
    fps = inputs.get("fps", 25)
    t = local_frame / fps

    def blank() -> Image.Image:
        return Image.new("RGBA", (W, H))

    roles: Layers = {}
    if disabled:
        return roles
    if component_id == "T01":
        end = inputs["opening_end"]
        variant = inputs.get("opening_variant", "B")
        exit_start = max(1.6, end - 0.68)
        phase = t if t < exit_start else 9.64 + (t - exit_start)
        if t >= end:
            return roles
        cfg: Inputs = {
            "size": [W, H],
            "fonts": inputs["fonts"],
            "support": inputs.get("subtitle", ""),
            "main": inputs.get("title", ""),
            "chapters": ["", ""],
            "captions": [{"time": [0, 0], "text": ""}],
            "opening_color": inputs.get("opening_color", [249, 248, 246]),
        }
        helper_cfg = {**cfg, "support": "", "main": ""}
        helper = _type_helper(json.dumps(helper_cfg, sort_keys=True))
        base = helper.render_subtitle(phase)
        if variant == "B":
            roles = {"wash": base["wash"], "border": base["border"]}
            enter = 1 if phase == 0 else ease(0.28, 0.64, phase)
            out = 1 - ease(9.64, 10.08, phase)
            for role, text, path, preferred, minimum, top, max_height in [
                (
                    "support",
                    cfg["support"],
                    cfg["fonts"]["support"],
                    64 * k / 2,
                    14 * k,
                    113.5,
                    44,
                ),
                (
                    "main",
                    cfg["main"],
                    cfg["fonts"]["main"],
                    149 * k / 2,
                    24 * k,
                    167.5,
                    100,
                ),
            ]:
                layer = blank()
                lines, size = _fit_opening(
                    text, path, preferred, minimum, 480 * k, max_height * k
                )
                if lines:
                    image = _text_block(
                        lines, path, size, (8, 8, 8, 255), role == "main"
                    )
                    progress = ease(0.96, 1.4, phase) if role == "main" else enter
                    opacity = progress * out
                    if role == "support":
                        _place_alpha(
                            layer,
                            image,
                            W / 2,
                            (top + blend(52, 0, enter) + 180 * ease(9.64, 10.08, phase))
                            * k
                            - 16,
                            opacity,
                            blur=5 * k * (1 - enter) + 6 * k * (1 - out),
                        )
                    else:
                        _place_alpha(
                            layer,
                            image,
                            W / 2,
                            (top + 100 * ease(9.64, 10.08, phase)) * k - 16,
                            opacity,
                            scale=blend(0.92, 1, progress),
                            blur=(1 - progress) * 8 * k + (1 - out) * 7 * k,
                        )
                roles[role] = layer
            return roles
        opacity = 1 - ease(end - 0.60, end - 0.12, t)
        roles = {"wash": base["wash"], "border": base["border"]}
        for role, text, size, top, minimum, max_height in [
            ("main", cfg["main"], 149, 120, 24, 80),
            ("support", cfg["support"], 82, 210, 16, 60),
        ]:
            layer = blank()
            if text:
                path = cfg["fonts"]["main" if role == "main" else "caption_bold"]
                lines, point = _fit_opening(
                    text, path, size * k / 2, minimum * k, 480 * k, max_height * k
                )
                im = _text_block(
                    lines,
                    path,
                    point,
                    (20, 70, 106, 255) if role == "main" else (12, 12, 12, 255),
                )
                _place_alpha(
                    layer, im, W / 2, top * k - 16, opacity, blur=2 * k * (1 - opacity)
                )
            roles[role] = layer
        return roles
    if component_id != "T05":
        raise ValueError("Unknown subtitle component")
    fonts = inputs["fonts"]
    caps = inputs.get("captions", [])
    for row in caps:
        a, b = row["time"]
        if not a <= t < b:
            continue
        layer = blank()
        text = row["text"]
        accent = row.get("emphasis", "")
        pos = text.find(accent) if accent else -1
        parts = (
            [(text[:pos], False), (accent, True), (text[pos + len(accent) :], False)]
            if pos >= 0
            else [(text, False)]
        )
        phase = row.get("color", "white") == "black"
        body = (30 if phase else 28) * k
        large = 35 * k
        length = sum(
            font(
                fonts["caption_bold"] if emph else fonts["caption"],
                large if emph else body,
            ).getlength(s)
            for s, emph in parts
        )
        if length > W * 0.94:
            factor = W * 0.94 / length
            if factor < 0.72:
                raise ValueError("Caption exceeds safe reading width")
            body *= factor
            large *= factor
            length = sum(
                font(
                    fonts["caption_bold"] if e else fonts["caption"],
                    large if e else body,
                ).getlength(s)
                for s, e in parts
            )
        x = (W - length) / 2
        baseline = row.get("baseline_540", 834) * k
        d = ImageDraw.Draw(layer)
        for s, e in parts:
            face = font(
                fonts["caption_bold"] if e else fonts["caption"], large if e else body
            )
            d.text(
                (round(x), round(baseline)),
                s,
                font=face,
                fill=(0, 151, 233, 255)
                if e
                else (12, 12, 12, 255)
                if phase
                else (255, 255, 255, 255),
                anchor="ls",
                stroke_width=max(1, round(k)),
                stroke_fill=(255, 255, 255, 220) if phase else (25, 25, 25, 190),
            )
            x += face.getlength(s)
        q = ease(a, a + 0.18, t) * (1 - ease(b - 0.08, b, t))
        if q < 1:
            layer = _blur_alpha(layer, (1 - q) * 2 * k)
            layer.putalpha(
                layer.getchannel("A").point([round(value * q) for value in range(256)])
            )
        roles["caption"] = layer
        break
    chapter = next(
        (r for r in reversed(inputs.get("chapters", [])) if r["time"] <= t), None
    )
    if chapter and chapter.get("text"):
        text = chapter["text"]
        face = font(fonts["caption_bold"], 16 * k)
        w = round(face.getlength(text) + 62 * k)
        layer = blank()
        small = Image.new("RGBA", (w + round(24 * k), round(65 * k)))
        d = ImageDraw.Draw(small)
        d.rounded_rectangle(
            (12 * k, 8 * k, w + 12 * k, 50 * k),
            radius=21 * k,
            fill=(255, 255, 255, 245),
        )
        d.ellipse((23 * k, 19 * k, 43 * k, 39 * k), fill=(0, 119, 214, 255))
        d.ellipse((28 * k, 24 * k, 38 * k, 34 * k), fill="white")
        d.text((52 * k, 17 * k), text, font=face, fill=(12, 12, 12, 255), anchor="lt")
        place_center(
            layer,
            small,
            W / 2,
            12 * k,
            ease(chapter["time"], chapter["time"] + 0.24, t),
        )
        roles["chapter"] = layer
    card = inputs.get("name_card")
    if card and card.get("enabled") and card.get("name"):
        description = card.get("description", "")
        legacy, names, name_size, descriptions, body_size = _fit_name_card(
            card["name"], description, fonts["caption_bold"], fonts["caption"], k
        )
        layer = blank()
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(
            (24 * k, 695 * k, 252 * k, 772 * k),
            radius=10 * k,
            fill=(255, 255, 255, 235),
        )
        d.rectangle((24 * k, 710 * k, 28 * k, 755 * k), fill=(0, 119, 214, 255))
        if legacy:
            d.text(
                (40 * k, 708 * k),
                card["name"],
                font=font(fonts["caption_bold"], 22 * k),
                fill=(12, 12, 12, 255),
            )
            d.text(
                (40 * k, 743 * k),
                description,
                font=font(fonts["caption"], 12 * k),
                fill=(100, 100, 100, 255),
            )
        else:
            _draw_left_lines(
                layer,
                names,
                fonts["caption_bold"],
                name_size,
                40 * k,
                706 * k,
                (12, 12, 12, 255),
            )
            top = (
                706 * k
                + _line_metrics(names, fonts["caption_bold"], name_size)[1]
                + 4 * k
            )
            _draw_left_lines(
                layer,
                descriptions,
                fonts["caption"],
                body_size,
                40 * k,
                top,
                (100, 100, 100, 255),
            )
        roles["name_card"] = layer
    return roles
