"""Text and optional picture layouts for public templates with material slots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .motion_library import atomic_json, sha256
from .video_editing_pipeline import run
from .video_editing_tutorial_surfaces import SIZE, _title

ENGINE = "tengli-editorial-suite"
VERSION = "tengli.editorial-suite/1"


@dataclass(frozen=True)
class Editorial:
    portrait: tuple[int, int, int, int]
    backdrop: str
    ink: str
    accent: str
    panel: str


STYLES = {
    "rotation-cards-v1": Editorial(
        (304, 200, 472, 840), "#201815", "#F7EBD8", "#CEAB72", "#3B2D26"
    ),
    "azl-panels-v1": Editorial(
        (62, 330, 486, 864), "#FBFAF6", "#191B25", "#2A55C9", "#EBE7DE"
    ),
    "chenxi-broll-v1": Editorial(
        (588, 260, 420, 746), "#F2E9D5", "#2B261C", "#8C7550", "#E2D4B4"
    ),
}


def use_editorial(template_id: str | None, assets: dict[str, dict]) -> bool:
    if template_id not in STYLES:
        return False
    photos = {row["sha256"] for row in assets.values() if row["kind"] == "image"}
    recordings = any(row["kind"] == "video" for row in assets.values())
    if template_id == "rotation-cards-v1":
        return len(photos) < 3
    if template_id == "azl-panels-v1":
        return recordings or not photos
    # The timing of a real recording is handled by the shared clock.
    return True


def bundle(template_id: str, planner_bundle: dict) -> dict:
    from dataclasses import asdict

    from .video_editing_tutorial_plan import digest

    return {
        "engine": ENGINE,
        "version": VERSION,
        "sha256": digest(
            {
                "planner": planner_bundle,
                "template": template_id,
                "layout": asdict(STYLES[template_id]),
                "renderer": sha256(Path(__file__)),
            }
        ),
    }


def sections(resolved: dict) -> list[dict]:
    """Only render words and media that the saved plan actually binds."""
    points = [{"start": 0.0, "text": resolved["title"]}]
    points.extend(
        {"start": float(row["time"]), "text": row["text"]}
        for row in resolved["chapters"]
    )
    points.extend(
        {"start": float(row["start"]), "text": row["text"]}
        for row in resolved["points"] + resolved["features"]
    )
    if resolved["conclusion"]:
        points.extend(
            {"start": float(row["start"]), "text": row["text"]}
            for row in resolved["conclusion"].values()
        )
    for row in resolved["materials"]:
        points.append(
            {
                "start": float(row["start"]),
                "text": row["spoken_text"],
                "image": row["path"],
            }
        )
    if len(points) == 1:
        for cue in resolved["captions"]:
            if cue["time"][0] - points[-1]["start"] >= 4:
                points.append({"start": float(cue["time"][0]), "text": cue["text"]})
    by_start = {round(point["start"], 3): point for point in points}
    return [
        point for at, point in sorted(by_start.items()) if at < resolved["duration"]
    ]


def draw_page(
    template_id: str, fonts: dict, title: str, pages: list[dict], index: int
) -> Image.Image:
    style = STYLES[template_id]
    image = Image.new("RGB", SIZE, style.backdrop)
    draw = ImageDraw.Draw(image)
    title_font = fonts["main"]
    x, y, w, h = style.portrait
    draw.rounded_rectangle(
        (x - 9, y - 9, x + w + 9, y + h + 9), radius=26, outline=style.accent, width=3
    )
    _title(draw, title, title_font, (60, 53), 950, 50, style.ink)
    draw.line((60, 176, 1018, 176), fill=style.accent, width=4)
    point = pages[index]
    if index == 0:
        return image
    has_image = "image" in point
    if template_id == "rotation-cards-v1":
        left, top, width, height = 114, 1118, 852, 394 if has_image else 230
        for offset in reversed(range(1, min(len(pages), 3))):
            pad = 26 * offset
            draw.rounded_rectangle(
                (left + pad, top - pad, left + width - pad, top + height - pad),
                radius=32,
                fill=style.panel,
                outline=style.accent,
                width=3,
            )
    elif template_id == "azl-panels-v1":
        left, top, width, height = 587, 344, 421, 480 if has_image else 235
        draw.line((565, 325, 565, 1204), fill=style.ink, width=2)
    else:
        left, top, width, height = 58, 320, 468, 560 if has_image else 270
        draw.line((72, 273, 72, 1280), fill=style.accent, width=3)
    draw.rounded_rectangle(
        (left, top, left + width, top + height),
        radius=18,
        fill=style.panel,
        outline=style.accent,
        width=2,
    )
    if has_image:
        with Image.open(point["image"]) as asset:
            picture = ImageOps.contain(asset.convert("RGB"), (width - 32, height - 134))
        image.paste(picture, (left + (width - picture.width) // 2, top + 112))
    _title(
        draw,
        point["text"],
        title_font,
        (left + 25, top + 31),
        width - 50,
        44,
        style.ink,
    )
    if template_id != "rotation-cards-v1":
        visible = pages[max(1, index - 2) : index]
        for i, previous in enumerate(visible):
            at = top + height + 48 + 115 * i
            draw.line(
                (left + 15, at - 8, left + width - 15, at - 8),
                fill=style.accent,
                width=2,
            )
            _title(
                draw,
                previous["text"],
                title_font,
                (left + 15, at),
                width - 30,
                29,
                style.ink,
            )
    return image


def _caption_file(root: Path, cues: list[dict]) -> Path:
    def time(value: float) -> str:
        ms = round(value * 1000)
        hours, minutes, seconds = ms // 3600000, ms // 60000 % 60, ms // 1000 % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms % 1000:03d}"

    path = root / "spoken.srt"
    rows = []
    for i, cue in enumerate(cues, 1):
        text = cue["text"].replace("<", "＜").replace(">", "＞")
        rows.append(f"{i}\n{time(cue['time'][0])} --> {time(cue['time'][1])}\n{text}\n")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def render(config: dict, out: Path, settings: Any, guard: Any) -> Path:
    from .video_editing_tutorial_render import concat_file, filter_path

    out.mkdir(parents=True, exist_ok=True)
    template_id = config["template_id"]
    source = config["source_path"]
    resolved, fonts = config["resolved"], config["fonts"]
    duration = resolved["duration"]
    pages = sections(resolved)
    tiles, spans = [], []
    starts = [point["start"] for point in pages] + [duration]
    for index, (start, end) in enumerate(zip(starts, starts[1:], strict=False)):
        tile = out / f"page-{index:03d}.png"
        draw_page(template_id, fonts, resolved["title"], pages, index).save(tile)
        tiles.append(tile)
        spans.append(end - start)
    manifest = concat_file(out / "pages.ffconcat", tiles, spans, images=True)
    x, y, width, height = STYLES[template_id].portrait
    graph = (
        f"[0:v]fps=30,scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[person];"
        f"[1:v]fps=30,format=yuv420p[page];[page][person]overlay={x}:{y}[visual]"
    )
    label = "visual"
    if config["source_subtitles"] == "none":
        subtitle = _caption_file(out, resolved["captions"])
        caption_font = ImageFont.truetype(fonts["caption"], 55).getname()[0]
        fontsdir = filter_path(Path(fonts["caption"]).parent)
        graph += (
            f";[visual]subtitles=filename='{filter_path(subtitle)}':fontsdir='{fontsdir}':"
            f"force_style='FontName={caption_font},FontSize=11,Outline=1,MarginV=32'[subtitled]"
        )
        label = "subtitled"
    final = out / "final.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-i",
            source,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            graph,
            "-map",
            f"[{label}]",
            "-map",
            "0:a:0",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            str(final),
        ],
        out,
        settings,
        guard,
        "editorial_style",
    )
    atomic_json(
        out / "render-receipt.json",
        {
            "final_sha256": sha256(final),
            "engine": ENGINE,
            "template_id": template_id,
            "sections": len(pages),
            "image_sections": sum("image" in page for page in pages),
        },
    )
    return final
