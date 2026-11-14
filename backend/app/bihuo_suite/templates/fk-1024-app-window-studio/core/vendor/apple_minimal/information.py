"""T02/T03/T04 editable information mechanisms; independent transparent roles.

Native measurements are 1080x1920. These are reference reconstructions, not
original author source. V02 presenter and T05 speech caption are parent-owned.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULTS: dict[str, dict[str, Any]] = {
    "T02": {
        "header": "3 项设置",
        "items": ["续航更长", "拍照更稳", "系统更顺"],
        "events": {
            "rows": [[29, 36], [78, 85], [185, 192]],
            "toggles": [[211, 214], [217, 220], [224, 227]],
            "exit": [235, 240],
        },
    },
    "T03": {
        "first": "不会设计",
        "second": "也能做",
        "events": {
            "quote": [5, 9],
            "first": [7, 13],
            "second": [12, 19],
            "exit": [246, 256],
        },
    },
    "T04": {
        "items": ["卖点排版", "产品展示", "整体配色"],
        "events": {
            "cards": [[8, 14], [33, 40], [61, 68]],
            "focus_handoffs": [[35, 39], [63, 67]],
            "exit": [113, 122],
        },
    },
}
FONT_NAMES = {
    "title": "思源黑体_CN_Bold--62383707c086.otf",
    "body": "Noto_Sans_SC_Medium--9c62ceb174d7.otf",
    "card": "Noto_Sans_SC_Bold--d1961be1161e.otf",
    "header": "Noto_Sans_SC_Bold--d1961be1161e.otf",
}


def ease(a: float, b: float, n: float) -> float:
    q = max(0.0, min(1.0, (n - a) / (b - a))) if b > a else float(n >= b)
    return q * q * (3 - 2 * q)


def mix(a: float, b: float, q: float) -> float:
    return a + (b - a) * q


@lru_cache(maxsize=64)
def _font(path: str | Path, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(1, round(size)))


def _fonts(inputs: dict[str, Any]) -> dict[str, str]:
    supplied = inputs.get("fonts", {})
    base = Path(__file__).resolve().parents[2] / "library/assets/fonts"
    return {
        key: str(
            supplied.get(key)
            or supplied.get(
                "main" if key == "title" else "caption" if key == "body" else key
            )
            or base / name
        )
        for key, name in FONT_NAMES.items()
    }


def _blank(size: Sequence[int]) -> Image.Image:
    return Image.new("RGBA", list(size))


def _ink(text: str, path: str | Path, size: float, color: Any) -> Image.Image:
    if not text:
        return Image.new("RGBA", (1, 1))
    f = _font(path, size)
    b = cast(tuple[int, int, int, int], f.getbbox(text, anchor="lt"))
    im = Image.new("RGBA", (b[2] - b[0] + 8, b[3] - b[1] + 8))
    d = ImageDraw.Draw(im)
    d.text((4 - b[0], 4 - b[1]), text, font=f, fill=color, anchor="lt")
    box = im.getchannel("A").getbbox()
    return im.crop(box)


def _put_ink(
    layer: Image.Image,
    text: str,
    path: str | Path,
    size: float,
    color: Any,
    x: float,
    y: float,
) -> tuple[int, int]:
    im = _ink(text, path, size, color)
    layer.alpha_composite(im, (round(x), round(y)))
    return im.size


def _wrap(
    text: str, path: str | Path, size: float, width: float, max_lines: int = 2
) -> list[str]:
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("Information text must be a short string")
    if not text:
        return []
    f = _font(path, size)
    lines = []
    line = ""
    for c in text:
        if c == "\n" or (line and f.getlength(line + c) > width):
            lines.append(line)
            line = "" if c == "\n" else c
        else:
            line += c
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        raise ValueError(
            "Information text exceeds measured reading space; "
            "shorten it or use another recipe"
        )
    return lines


def _phase(
    layer: Image.Image,
    n: float,
    interval: Sequence[float],
    exit_interval: Sequence[float] | None = None,
    blur: float = 12,
    scale_from: float = 0.96,
    anchor: tuple[float, float] | None = None,
) -> Image.Image:
    p = ease(interval[0], interval[1], n)
    out = 1 - ease(exit_interval[0], exit_interval[1], n) if exit_interval else 1
    if p * out <= 0:
        return _blank(layer.size)
    q = p * out
    if scale_from != 1 and p < 1:
        s = mix(scale_from, 1, p)
        w, h = layer.size
        small = layer.resize(
            (max(1, round(w * s)), max(1, round(h * s))), Image.Resampling.LANCZOS
        )
        dest = _blank(layer.size)
        ax, ay = anchor or (w / 2, h / 2)
        dest.alpha_composite(small, (round(ax * (1 - s)), round(ay * (1 - s))))
        layer = dest
    if q < 1:
        # Blur premultiplied color to keep transparent card/text edges clean on white.
        layer = (
            layer.convert("RGBa")
            .filter(ImageFilter.GaussianBlur((1 - q) * blur))
            .convert("RGBA")
        )
        layer.putalpha(layer.getchannel("A").point(lambda a: round(a * q)))
    return layer


def _quote(size: Sequence[int], k: float, color: Any) -> Image.Image:
    layer = _blank(size)
    d = ImageDraw.Draw(layer)
    # Independently editable double-quotation graphic, traced from source contour.
    points = [
        (47, 0),
        (48, 18),
        (32, 25),
        (23, 37),
        (19, 51),
        (48, 51),
        (48, 89),
        (0, 89),
        (0, 54),
        (3, 35),
        (11, 20),
        (26, 8),
    ]
    for x in [140, 201]:
        d.polygon(
            [(round((x + px) * k), round((381 + py) * k)) for px, py in points],
            fill=color,
        )
    return layer


def _icon(
    layer: Image.Image, kind: str, x: float, y: float, k: float, color: Any
) -> None:
    d = ImageDraw.Draw(layer)
    w = max(1, round(2 * k))

    def line(points: list[tuple[float, float]]) -> None:
        d.line(
            [(round((x + a) * k), round((y + b) * k)) for a, b in points],
            fill=color,
            width=w,
            joint="curve",
        )

    if kind == "checklist":
        for dy in [0, 10, 20]:
            line([(0, dy + 3), (3, dy + 6), (8, dy)])
            line([(12, dy + 3), (26, dy + 3)])
    elif kind == "cube":
        line(
            [
                (13, 0),
                (26, 7),
                (26, 22),
                (13, 30),
                (0, 22),
                (0, 7),
                (13, 0),
                (13, 15),
                (26, 7),
            ]
        )
        line([(0, 7), (13, 15), (13, 30)])
    else:
        d.ellipse(
            (round(x * k), round(y * k), round((x + 28) * k), round((y + 24) * k)),
            outline=color,
            width=w,
        )
        for dx, dy in [(7, 7), (15, 5), (22, 10)]:
            d.ellipse(
                (
                    round((x + dx) * k),
                    round((y + dy) * k),
                    round((x + dx + 3) * k),
                    round((y + dy + 3) * k),
                ),
                fill=color,
            )


def render_subtitle(
    component_id: str, local_frame: int, inputs: dict[str, Any], disabled: bool = False
) -> dict[str, Image.Image]:
    """Return fresh named RGBA layers; text, fonts and frame events are replaceable.

    `inputs`: size, fonts, items/header or first/second, events (native frame units).
    All roles are independent; returned images never contain presenter or backdrop.
    """
    if component_id not in DEFAULTS:
        raise ValueError("Unknown information component")
    size = tuple(inputs.get("size", [1080, 1920]))
    W, H = size
    if abs(W / H - 9 / 16) > 0.001:
        raise ValueError(
            "Information suite currently supports measured portrait 9:16 only"
        )
    k = W / 1080
    fonts = _fonts(inputs)
    cfg = {**DEFAULTS[component_id], **inputs}
    events = {**DEFAULTS[component_id]["events"], **inputs.get("events", {})}
    n = float(local_frame)
    accent = tuple(inputs.get("accent", [1, 112, 227])) + (255,)
    gray = (240, 240, 240, 255)
    black = (12, 12, 12, 255)
    roles = {}
    if component_id == "T02":
        items = cfg["items"]
        if not isinstance(items, list) or len(items) > 4:
            raise ValueError("Settings component accepts up to four rows")
        header = _blank(size)
        _put_ink(
            header,
            cfg.get("header", ""),
            fonts["header"],
            31 * k,
            accent,
            136 * k,
            384 * k,
        )
        roles["settings-header"] = _phase(
            header, n, [0, 0], events.get("exit"), blur=10 * k, scale_from=1
        )
        row_events = events["rows"]
        toggle_events = events["toggles"]
        if len(row_events) < len(items) or len(toggle_events) < len(items):
            raise ValueError("Each settings row requires entry and toggle clock")
        for i, text in enumerate(items):
            top = 442 + 128 * i
            bg = _blank(size)
            d = ImageDraw.Draw(bg)
            d.rounded_rectangle(
                (134 * k, top * k, 946 * k, (top + 114) * k), radius=31 * k, fill=gray
            )
            label = _blank(size)
            lines = _wrap(text, fonts["body"], 42 * k, 600 * k)
            total = len(lines) * 50 * k - 10 * k if lines else 0
            y = (top + 57) * k - total / 2
            for line in lines:
                _put_ink(label, line, fonts["body"], 42 * k, black, 168 * k, y)
                y += 50 * k
            switch = _blank(size)
            q = ease(toggle_events[i][0], toggle_events[i][1], n)
            off = (211, 211, 211)
            fill = tuple(round(mix(off[j], accent[j], q)) for j in range(3)) + (255,)
            d = ImageDraw.Draw(switch)
            d.rounded_rectangle(
                (813 * k, (top + 28) * k, 916 * k, (top + 87) * k),
                radius=29.5 * k,
                fill=fill,
            )
            cx = mix(839, 890, q) * k
            cy = (top + 57.5) * k
            r = 24 * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white")
            for role, im in [("background", bg), ("label", label), ("switch", switch)]:
                roles[f"settings-{i}-{role}"] = _phase(
                    im,
                    n,
                    row_events[i],
                    events.get("exit"),
                    blur=9 * k,
                    scale_from=0.98,
                    anchor=(540 * k, (top + 57) * k),
                )
    elif component_id == "T03":
        first = cfg.get("first", "")
        second = cfg.get("second", "")
        first_lines = _wrap(first, fonts["title"], 93 * k, 812 * k)
        second_lines = _wrap(second, fonts["title"], 93 * k, 812 * k)
        if len(first_lines) + len(second_lines) > 3:
            raise ValueError(
                "Quote mechanism supports at most three natural text lines"
            )
        quote = _quote(size, k, (207, 228, 249, 255))
        roles["quote-mark"] = _phase(
            quote,
            n,
            events["quote"],
            events.get("exit"),
            blur=10 * k,
            anchor=(140 * k, 381 * k),
        )
        top = 513 * k
        for key, lines, color in [
            ("first", first_lines, black),
            ("second", second_lines, accent),
        ]:
            layer = _blank(size)
            for line in lines:
                _put_ink(layer, line, fonts["title"], 93 * k, color, 137 * k, top)
                top += 107 * k
            roles[f"quote-{key}"] = _phase(
                layer,
                n,
                events[key],
                events.get("exit"),
                blur=12 * k,
                scale_from=0.97,
                anchor=(137 * k, 513 * k),
            )
    elif component_id == "T04":
        items = cfg["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 3:
            raise ValueError("Feature-card mechanism accepts one to three items")
        boxes = [[134, 387, 946, 579], [134, 597, 530, 789], [550, 597, 946, 789]]
        handoffs = events["focus_handoffs"]
        q1 = ease(handoffs[0][0], handoffs[0][1], n)
        q2 = ease(handoffs[1][0], handoffs[1][1], n)
        active = [1 - q1, q1 * (1 - q2), q2]
        icons = cfg.get("icons", ["checklist", "cube", "palette"])
        for i, text in enumerate(items):
            x, y, r, b = boxes[i]
            focus = active[i]
            bg = _blank(size)
            d = ImageDraw.Draw(bg)
            fill = tuple(round(mix(gray[j], accent[j], focus)) for j in range(3)) + (
                255,
            )
            d.rounded_rectangle((x * k, y * k, r * k, b * k), radius=30 * k, fill=fill)
            label = _blank(size)
            color = tuple(round(mix(black[j], 255, focus)) for j in range(3)) + (255,)
            lines = _wrap(text, fonts["card"], 45 * k, (r - x - 76) * k)
            top = (y + 115) * k if len(lines) <= 1 else (y + 85) * k
            for line in lines:
                _put_ink(label, line, fonts["card"], 45 * k, color, (x + 38) * k, top)
                top += 52 * k
            icon = _blank(size)
            iconcolor = tuple(round(mix(120, 255, focus)) for _ in range(3)) + (255,)
            _icon(
                icon,
                icons[i] if i < len(icons) else "cube",
                x + 50,
                y + 46,
                k,
                iconcolor,
            )
            for role, im in [("background", bg), ("label", label), ("icon", icon)]:
                roles[f"feature-{i}-{role}"] = _phase(
                    im,
                    n,
                    events["cards"][i],
                    events.get("exit"),
                    blur=12 * k,
                    scale_from=0.96,
                    anchor=((x + r) / 2 * k, (y + b) / 2 * k),
                )
    if disabled:
        return {role: _blank(size) for role in roles}
    return roles
