from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

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
    native_box: Box | None = None
    backdrop: str = "#14161B"
    edge: str = "#555960"
    frame_style: str = "line"


def _native(
    name: str,
    screen: Box,
    origin: tuple[int, int],
    width: int,
    backdrop: str,
    edge: str,
    frame_style: str,
) -> Surface:
    # Retain the whole original render, including moving elements and subtitles.
    return Surface(
        name,
        screen,
        native_box=(*origin, width, width * 16 // 9),
        backdrop=backdrop,
        edge=edge,
        frame_style=frame_style,
    )


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
        "magazine", (52, 302, 976, 522), (82, 916, 402, 586), 0, True, 318
    ),
    "apple-minimal-v1": _native(
        "apple-launch",
        (46, 176, 988, 528),
        (270, 792),
        540,
        "#FAFBFF",
        "#BECFE9",
        "window",
    ),
    "knowledge-talk-v1": _native(
        "knowledge-argument",
        (54, 1158, 972, 520),
        (270, 104),
        540,
        "#20201E",
        "#F0EAE1",
        "line",
    ),
    "presenter-openings-v1": _native(
        "presenter-opening",
        (34, 1248, 1012, 542),
        (216, 48),
        648,
        "#272019",
        "#B49176",
        "border",
    ),
    "rotation-cards-v1": _native(
        "rotation-cards",
        (76, 214, 928, 496),
        (298, 774),
        486,
        "#201713",
        "#D1AA6E",
        "stack",
    ),
    "unified-chapter-v1": _native(
        "chapter-navigation",
        (56, 1228, 968, 518),
        (100, 84),
        576,
        "#251F23",
        "#E9A9B6",
        "tab",
    ),
    "unified-paper-typewriter-v1": _native(
        "paper-typewriter",
        (48, 154, 984, 526),
        (306, 786),
        468,
        "#D9D6C8",
        "#737266",
        "grid",
    ),
    "chenxi-broll-v1": _native(
        "operation-broll",
        (32, 214, 1016, 544),
        (158, 815),
        504,
        "#25241D",
        "#ECDBAA",
        "tab",
    ),
    "bihuo-08-v1": _native(
        "meadow-rays",
        (44, 228, 992, 532),
        (306, 838),
        468,
        "#161815",
        "#A4A97A",
        "rays",
    ),
    "bihuo-09-v1": _native(
        "scroll-paper",
        (66, 1110, 948, 506),
        (70, 116),
        504,
        "#F4EBD6",
        "#B99A63",
        "stack",
    ),
    "bihuo-11-v1": _native(
        "old-letter",
        (60, 194, 960, 514),
        (306, 810),
        468,
        "#E8DFCE",
        "#9F8161",
        "stack",
    ),
    "bihuo-13-v1": _native(
        "celadon", (60, 1094, 960, 514), (496, 138), 504, "#CEE0D6", "#7FA28D", "tab"
    ),
    "bihuo-14-v1": _native(
        "teal-news",
        (88, 246, 904, 484),
        (306, 858),
        468,
        "#0B1A18",
        "#39A486",
        "window",
    ),
    "bihuo-15-v1": _native(
        "blue-halo", (50, 160, 980, 524), (270, 788), 540, "#EBEFFB", "#99B8EC", "halo"
    ),
    "bihuo-16-v1": _native(
        "milk-blue", (62, 1160, 956, 512), (288, 102), 504, "#E3EDF2", "#8CAFBD", "halo"
    ),
    "bihuo-19-v1": _native(
        "quantum", (48, 1122, 984, 526), (76, 130), 504, "#E5E9EF", "#6287C8", "tab"
    ),
    "bihuo-23-v1": _native(
        "navy-news",
        (48, 218, 984, 526),
        (386, 801),
        486,
        "#111D38",
        "#DD8955",
        "ticker",
    ),
    "bihuo-24-v1": _native(
        "celadon-bilingual",
        (48, 1102, 984, 526),
        (456, 98),
        540,
        "#E8F4EB",
        "#729588",
        "line",
    ),
    "bihuo-26-v1": _native(
        "indigo-notes",
        (68, 194, 944, 506),
        (298, 827),
        486,
        "#E7E8EF",
        "#7B819F",
        "stack",
    ),
    "bihuo-27-v1": _native(
        "berry-night",
        (52, 228, 976, 522),
        (270, 826),
        540,
        "#241E3F",
        "#B799C9",
        "border",
    ),
    "bihuo-28-v1": _native(
        "neon-night",
        (60, 1128, 960, 514),
        (470, 102),
        504,
        "#1B1239",
        "#B3D462",
        "ticker",
    ),
    "bihuo-29-v1": _native(
        "violet-window",
        (66, 234, 948, 506),
        (288, 858),
        504,
        "#2A1649",
        "#A17BDC",
        "grid",
    ),
    "bihuo-32-v1": _native(
        "copper-business",
        (54, 1106, 972, 520),
        (288, 104),
        504,
        "#27201C",
        "#BF946B",
        "border",
    ),
    "bihuo-33-v1": _native(
        "vibrant-news",
        (48, 1124, 984, 526),
        (288, 124),
        504,
        "#22213A",
        "#DFBD5F",
        "grid",
    ),
    "bihuo-34-v1": _native(
        "yellow-white",
        (36, 1246, 1008, 540),
        (216, 60),
        648,
        "#151515",
        "#D3BA61",
        "line",
    ),
    "bihuo-40-v1": _native(
        "white-card",
        (46, 1114, 988, 530),
        (270, 95),
        540,
        "#EDECEA",
        "#FFFFFF",
        "stack",
    ),
    "bihuo-47-v1": _native(
        "business-rays",
        (42, 1058, 996, 534),
        (298, 60),
        486,
        "#151820",
        "#87939C",
        "rays",
    ),
    "bihuo-48-v1": _native(
        "materials-layout",
        (40, 1180, 1000, 536),
        (428, 132),
        540,
        "#E6EBE6",
        "#FFFFFF",
        "stack",
    ),
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


def native_chrome(layout: Surface) -> Image.Image:
    """Style the recording frame while reserving the native video panel."""
    img = Image.new("RGBA", SIZE, layout.backdrop)
    draw = ImageDraw.Draw(img)
    x, y, width, height = layout.viewport
    edge, style = layout.edge, layout.frame_style
    if style == "grid":
        for grid_x in range(0, SIZE[0], 54):
            draw.line((grid_x, 0, grid_x, SIZE[1]), fill=edge, width=1)
        for grid_y in range(0, SIZE[1], 54):
            draw.line((0, grid_y, SIZE[0], grid_y), fill=edge, width=1)
    elif style == "rays":
        for end_x in range(-950, 2200, 180):
            draw.line((540, 960, end_x, 0), fill=edge, width=1)
            draw.line((540, 960, end_x, 1920), fill=edge, width=1)
    elif style == "stack":
        for shift in (26, 12):
            draw.rounded_rectangle(
                (x + shift, y + shift, x + width + shift, y + height + shift),
                radius=18,
                outline=edge,
                width=3,
            )
    elif style == "halo":
        for pad in (19, 13, 7):
            draw.rounded_rectangle(
                (x - pad, y - pad, x + width + pad, y + height + pad),
                radius=24,
                outline=edge,
                width=2,
            )
    elif style in {"window", "ticker"}:
        draw.rounded_rectangle(
            (x - 6, y - 45, x + width + 6, y + 18), radius=13, fill=edge
        )
        for position in (x + 18, x + 41, x + 64):
            draw.ellipse(
                (position, y - 28, position + 10, y - 18), fill=layout.backdrop
            )
    elif style == "tab":
        draw.rounded_rectangle((x + 22, y - 22, x + 173, y + 12), radius=9, fill=edge)
    draw.rounded_rectangle(
        (x - 7, y - 7, x + width + 7, y + height + 7), radius=18, fill=edge
    )
    assert layout.native_box is not None
    nx, ny, nw, nh = layout.native_box
    draw.rounded_rectangle(
        (nx - 5, ny - 5, nx + nw + 5, ny + nh + 5), radius=16, outline=edge, width=3
    )
    return img


def large_chrome(layout: Surface, template_id: str, step: dict) -> Image.Image:
    backdrop = layout.backdrop if layout.native_box else "#F7F8F1"
    image = Image.new("RGBA", SIZE, backdrop)
    draw = ImageDraw.Draw(image)
    label = re.sub(r"^\s*\d+[_.、\s-]*", "", step["label"]).strip()
    light = sum(ImageColor.getrgb(backdrop)[:3]) >= 3 * 132
    title_font, _ = fonts_for(template_id)
    _title(
        draw,
        label,
        title_font,
        (54, 47),
        972,
        47,
        "#171A1B" if light else "#FFFFFF",
    )
    return image


def chrome(
    layout: Surface, template_id: str, step: dict, labels: list[str]
) -> Image.Image:
    if layout.native_box:
        return native_chrome(layout)

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
