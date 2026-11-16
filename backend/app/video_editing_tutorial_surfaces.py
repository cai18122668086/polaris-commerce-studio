from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (1080, 1920)
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Surface:
    name: str
    viewport: Box
    presenter: Box | None = None
    presenter_radius: int = 0
    replaces_caption: bool = False
    caption_margin: int = 240
    caption_color: str = "FFFFFF"
    caption_outline: str = "171717"
    pad_color: str = "white"


# Coordinates belong to each template, not to the shared tutorial clock.
_SURFACES = {
    "bihuo-02-v1": Surface("capsule", (66, 500, 948, 508)),
    "bihuo-03-v1": Surface("application-top", (118, 895, 844, 452)),
    "bihuo-04-v1": Surface("application", (120, 510, 840, 450)),
    "bihuo-10-v1": Surface(
        "paper-gallery", (44, 236, 992, 532), (286, 1022, 508, 504), 38, True, 246
    ),
    "bihuo-36-v1": Surface(
        "silver", (70, 930, 940, 504), (246, 252, 588, 626), 28, True, 248
    ),
    "product-explainer-v1": Surface("product", (24, 960, 1032, 552)),
    "azl-panels-v1": Surface(
        "magazine", (52, 302, 976, 522), (82, 916, 402, 586), 0, True, 247
    ),
    "apple-minimal-v1": Surface("apple", (72, 770, 936, 502)),
}


def surface(template_id: str) -> Surface:
    # Unmapped templates retain their native picture and typography around an inset.
    return _SURFACES.get(template_id, Surface("inset", (72, 972, 936, 502)))


def fonts_for(template_id: str) -> tuple[str, str]:
    from .bihuo_suite.registry import fonts, is_template

    faces = fonts(template_id if is_template(template_id) else "bihuo-02-v1")
    caption = faces.get("caption") or faces.get("bold") or faces["body"]
    return faces.get("title") or faces.get("bold") or caption, caption


def _title(
    draw: ImageDraw.ImageDraw,
    text: str,
    path: str,
    position: tuple[int, int],
    width: int,
    size: int,
    fill: str,
) -> None:
    from .bihuo_suite.conditional_layout import _label

    try:
        result = _label(text, path, width, tuple(range(size, 23, -3)), 2)
    except ValueError:
        # Asset filenames can exceed a decorative label. Keep the clip intact.
        face = ImageFont.truetype(path, 28)
        text = text.replace("\n", " ")
        while text and face.getlength(text + "…") > width:
            text = text[:-1]
        result = {"lines": [text + "…"], "size": 28}
    face = ImageFont.truetype(path, result["size"])
    x, y = position
    for line in result["lines"]:
        draw.text((x, y), line, font=face, fill=fill)
        y += result["size"] + 7


def chrome(
    layout: Surface, template_id: str, step: dict, labels: list[str]
) -> Image.Image:
    import re

    title_font, caption_font = fonts_for(template_id)
    index = step["index"]
    label = re.sub(r"^\s*\d+[_.、\s-]*", "", step["label"]).strip()
    x, y, width, height = layout.viewport
    if layout.name == "paper-gallery":
        from .bihuo_suite.registry import runtime

        img = runtime(template_id).F.paper().copy()
    elif layout.name == "silver":
        from .bihuo_suite.registry import runtime

        img = runtime(template_id).E.stage().copy()
    else:
        img = Image.new(
            "RGBA", SIZE, "white" if layout.name == "magazine" else (0, 0, 0, 0)
        )
    draw = ImageDraw.Draw(img)
    if layout.name == "capsule":
        # Preserve the original title, moving portrait and highlighted subtitles.
        draw.rounded_rectangle((50, 436, 1031, 1024), radius=32, fill="#FFFFFF")
        draw.rounded_rectangle((74, 448, 133, 485), radius=18, fill="#285CE3")
        draw.text(
            (90, 447),
            str(index),
            font=ImageFont.truetype(caption_font, 27),
            fill="white",
        )
        _title(draw, label, title_font, (147, 444), 820, 31, "#202126")
    elif layout.name in {"application", "application-top"}:
        if layout.name == "application":
            draw.rounded_rectangle((111, 354, 969, 1007), radius=28, fill="#EEEEEF")
            draw.text(
                (146, 388),
                f"{index:02d} / {len(labels):02d}",
                font=ImageFont.truetype(caption_font, 30),
                fill="#326CB5",
            )
            _title(draw, label, title_font, (146, 434), 785, 44, "#22242B")
        else:
            draw.rounded_rectangle((107, 830, 975, 1363), radius=26, fill="#EEEEEF")
            _title(draw, label, title_font, (145, 845), 778, 34, "#253656")
    elif layout.name == "paper-gallery":
        draw.rounded_rectangle((34, 206, 1046, 785), radius=24, fill="#FCF7E8")
        draw.polygon([(124, 70), (952, 45), (963, 160), (111, 186)], fill="#EFC94C")
        draw.polygon(
            [(108, 59), (936, 36), (944, 145), (99, 168)],
            fill="#21212A",
            outline="#FFFBEC",
            width=3,
        )
        _title(draw, label, title_font, (156, 73), 746, 54, "#FFFFFF")
        # The original gallery demotes examples to earlier slots. Keep the step
        # markers there without displaying a second copy of the recording.
        for offset, previous in enumerate(labels[max(0, index - 3) : index]):
            left = 44 + offset * 333
            accent = offset == min(index - 1, 2)
            draw.rounded_rectangle(
                (left, 814, left + 318, 965),
                radius=18,
                fill="#FFF4D4" if accent else "#E9D5B5",
            )
            _title(
                draw,
                re.sub(r"^\s*\d+[_.、\s-]*", "", previous),
                title_font,
                (left + 16, 845),
                284,
                32,
                "#3D3023",
            )
    elif layout.name == "silver":
        draw.rounded_rectangle(
            (x - 10, y - 10, x + width + 10, y + height + 10),
            radius=28,
            fill="#F3F2F5",
            outline="#7E8088",
            width=2,
        )
        _title(draw, label, title_font, (75, 105), 920, 55, "#282830")
        draw.line((76, 203, 1002, 203), fill="#A58B37", width=3)
    elif layout.name == "magazine":
        dark = index % 3 == 0
        ink = "#F9F8F3" if dark else "#1A1A1D"
        draw.rectangle((0, 0, 1080, 1920), fill="#171820" if dark else "#FCFBF8")
        draw.line((52, 107, 1028, 107), fill=ink, width=3)
        draw.text(
            (56, 47), f"{index:02d}", font=ImageFont.truetype(title_font, 38), fill=ink
        )
        _title(draw, label, title_font, (54, 142), 972, 71, ink)
        draw.rectangle((48, 298, 1032, 828), outline=ink, width=2)
        draw.rectangle((52, 900, 511, 1518), fill="#242C37" if dark else "#EDEBE4")
        for offset, previous in enumerate(
            labels[max(0, index - 2) : index + 1], start=max(1, index - 1)
        ):
            top = 930 + (offset - max(1, index - 1)) * 124
            selected = offset == index
            draw.rectangle(
                (560, top, 1028, top + 98),
                fill="#2958CE" if selected else ("#252638" if dark else "#EEEAE1"),
            )
            color = "#FFFFFF" if selected else ink
            draw.text(
                (577, top + 29),
                f"{offset:02d}",
                font=ImageFont.truetype(caption_font, 26),
                fill=color,
            )
            _title(
                draw,
                re.sub(r"^\s*\d+[_.、\s-]*", "", previous),
                title_font,
                (633, top + 25),
                366,
                30,
                color,
            )
        draw.line((560, 1360, 1028, 1360), fill="#ECCC5D", width=6)
    else:
        # A small border on the native picture preserves the rest of its composition.
        edge = "#0E1118" if layout.name == "product" else "#262A33"
        draw.rounded_rectangle(
            (x - 7, y - 7, x + width + 7, y + height + 7), radius=16, fill=edge
        )
    return img


def presenter_mask(layout: Surface, path: Path) -> None:
    assert layout.presenter is not None
    width, height = layout.presenter[2:]
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=layout.presenter_radius, fill=255
    )
    mask.save(path)
