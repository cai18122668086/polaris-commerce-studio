"""Short-video cover composition: keyframe, 3:4 crop, layout, exact title type.

Rules live in ``backend/skill_sources/video-cover-douyin-xhs`` (adapted from the
MIT projects JimLiu/baoyu-skills and alextangson/directors-chair, see its
SOURCES.md). This module is pure image work: no network, no database, so every
rule below is covered by offline tests.

The title is never drawn by a model. A background (the real keyframe, or an AI
repaint of it) gets the exact title typeset with the site's own font, and a
candidate only counts when every check in ``verify`` passes:

* text: the rendered lines joined back equal the cover text, and every
  character has a real glyph in the font (no tofu boxes);
* face: no text box touches the presenter's face (re-detected on the final
  background, expanded by a safety margin);
* design colours: nothing we add (text, outline, shadow, plate, highlight) is
  blue or purple;
* size: 1080x1440.

The picture's own colours (a blue shirt, a blue wall) are only reported, never
failed: ``picture_cool_share`` counts saturated blue/purple outside the
presenter box and the caller shows a hint above ``PICTURE_COOL_HINT``.
"""

from __future__ import annotations

import colorsys
import json
import math
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

CANVAS = (1080, 1440)
FONT_PATH = (
    Path(__file__).parent
    / "bihuo_suite/templates/fk-1104-know-white-capsule/fonts"
    / "62383707c086-思源黑体_CN_Bold--62383707c086.otf"
)
MIN_FONT = round(CANVAS[0] * 0.07)  # 200 px thumbnail still readable
LINE_GAP = 1.18
MAX_TEXT_CHARS = 40
PICTURE_COOL_HINT = 0.35

DARK_TEXT = "#1F1A17"
LIGHT_TEXT = "#FFFFFF"
HIGHLIGHT_ON_DARK_TEXT = "#E8742A"  # 熔光橙, used with dark text
HIGHLIGHT_ON_LIGHT_TEXT = "#F2C14E"  # 暖黄, used with white text
SHADOW = "#140F0C"
PLATE_DARK = (20, 15, 12, 115)
PLATE_LIGHT = (255, 250, 244, 180)
OUTLINE_LIGHT = "#FFF8F0"

Layout = Literal["top", "bottom", "side", "center"]
Box = tuple[int, int, int, int]

# Normalised title zones, from references/layouts.md.
ZONES: dict[str, tuple[float, float, float, float]] = {
    "top": (0.07, 0.07, 0.93, 0.36),
    "bottom": (0.07, 0.58, 0.93, 0.90),
    "side_left": (0.06, 0.18, 0.50, 0.78),
    "side_right": (0.50, 0.18, 0.94, 0.78),
    "center": (0.08, 0.34, 0.92, 0.66),
}
MAX_LINES = {"top": 3, "bottom": 3, "side": 4, "center": 3}

NO_LINE_START = set("，。！？、；：」』）》】…—·,.!?;:)]%")
NO_LINE_END = set("「『（《【([")
# Particles that belong to the word before them never start a line.
PARTICLES = set("的了着吗呢吧啊地得么")


class CoverComposeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------- faces


def _px(box: tuple[float, float, float, float], size: tuple[int, int]) -> Box:
    w, h = size
    return (round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h))


FACE_MARGIN_CAP = 48


def forbidden_zone(face: Box | None, size: tuple[int, int] = CANVAS) -> Box | None:
    """Face box grown 15% left/right, 25% up, 10% down, each at most 48 px.

    The cap keeps a close-up (a face half the frame wide) from turning the
    whole picture into a no-text zone; the face itself is always kept clear.
    """

    if face is None:
        return None
    x0, y0, x1, y1 = face
    w, h = x1 - x0, y1 - y0
    cap = FACE_MARGIN_CAP
    return (
        max(0, round(x0 - min(w * 0.15, cap))),
        max(0, round(y0 - min(h * 0.25, cap))),
        min(size[0], round(x1 + min(w * 0.15, cap))),
        min(size[1], round(y1 + min(h * 0.10, cap))),
    )


def presenter_zone(face: Box | None, size: tuple[int, int] = CANVAS) -> Box | None:
    """Rough head-and-body box: the picture check ignores it (clothes are not ours)."""

    if face is None:
        return None
    x0, y0, x1, y1 = face
    w, h = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2
    return (
        max(0, round(cx - w * 1.6)),
        max(0, round(y0 - h * 0.4)),
        min(size[0], round(cx + w * 1.6)),
        size[1],
    )


def intersection(a: Box, b: Box) -> int:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


# OpenCV 5's new DNN engine makes no thread-safety promise and covers run in
# parallel background threads, so every detector call goes through this lock
# and OpenCV keeps a single internal thread.
_CV_LOCK = threading.Lock()


@lru_cache(maxsize=4)
def _detector(size: tuple[int, int]) -> Any:  # pragma: no cover - needs OpenCV
    import cv2

    from .bihuo_suite.subject import FaceDetector, model_available

    if not model_available():
        return None
    cv2.setNumThreads(1)
    scale = 4 if min(size) >= 720 else 2
    return FaceDetector(size=size, scale=scale)


def detect_face(image: Image.Image) -> tuple[Box, float] | None:
    """Largest confident face, or None when the model is unavailable."""

    try:
        with _CV_LOCK:
            detector = _detector(image.size)
            if detector is None:
                return None
            return detector.detect(image.convert("RGB"))
    except Exception:  # detection never fails a cover
        return None


# -------------------------------------------------------------------- frames


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise CoverComposeError(
            "COVER_SOURCE_UNREADABLE", "视频读不出来，换一条视频试试。"
        ) from None


def sample_times(duration: float, count: int = 12) -> list[float]:
    """Evenly inside 5%-95% so fades at either end are skipped."""

    if duration <= 0:
        return [0.0]
    start, end = duration * 0.05, duration * 0.95
    if count == 1:
        return [round((start + end) / 2, 3)]
    step = (end - start) / (count - 1)
    return [round(start + step * i, 3) for i in range(count)]


def extract_frame(video: Path, at: float, target: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(target),
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if not target.exists() or target.stat().st_size == 0:
        raise CoverComposeError("COVER_SOURCE_UNREADABLE", "没能从视频里取到画面。")
    return target


def sharpness(image: Image.Image) -> float:
    gray = image.convert("L").resize((270, round(270 * image.height / image.width)))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def frame_score(image: Image.Image, face: tuple[Box, float] | None) -> float:
    """Face confidence x size suitability x sharpness (SKILL.md step 1)."""

    sharp = math.log1p(sharpness(image))
    if face is None:
        return sharp * 0.1
    (x0, _, x1, _), confidence = face
    ratio = (x1 - x0) / image.width
    if 0.12 <= ratio <= 0.40:
        fit = 1.0
    else:
        distance = 0.12 - ratio if ratio < 0.12 else ratio - 0.40
        fit = max(0.05, 1 - distance * 4)
    return confidence * fit * sharp


@dataclass
class Keyframe:
    image: Image.Image
    face: Box | None
    at: float
    score: float


def pick_keyframe(video: Path, workdir: Path, count: int = 12) -> Keyframe:
    duration = probe_duration(video)
    best: Keyframe | None = None
    for index, at in enumerate(sample_times(duration, count)):
        try:
            path = extract_frame(video, at, workdir / f"frame-{index:02d}.jpg")
        except CoverComposeError:
            continue
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        face = detect_face(image)
        score = frame_score(image, face)
        if best is None or score > best.score:
            best = Keyframe(image, face[0] if face else None, at, score)
        path.unlink(missing_ok=True)
    if best is None:
        raise CoverComposeError("COVER_SOURCE_UNREADABLE", "没能从视频里取到画面。")
    return best


def _window(image: Image.Image) -> tuple[int, int]:
    w, h = image.size
    target = CANVAS[0] / CANVAS[1]
    return (round(h * target), h) if w / h > target else (w, round(w / target))


def _crop_face(face: Box | None, left: int, top: int, cw: int, ch: int) -> Box | None:
    if not face:
        return None
    sx, sy = CANVAS[0] / cw, CANVAS[1] / ch
    moved = (
        round((face[0] - left) * sx),
        round((face[1] - top) * sy),
        round((face[2] - left) * sx),
        round((face[3] - top) * sy),
    )
    box = (
        max(0, moved[0]),
        max(0, moved[1]),
        min(CANVAS[0], moved[2]),
        min(CANVAS[1], moved[3]),
    )
    return box if box[2] > box[0] and box[3] > box[1] else None


def _whole_face(face: Box, window: tuple[int, int], size: tuple[int, int]) -> bool:
    """The face and some headroom stay inside the window."""

    left, top = window
    headroom = min(48, (face[3] - face[1]) * 0.12)
    return (
        face[0] >= left
        and face[2] <= left + size[0]
        and face[1] - headroom >= top
        and face[3] <= top + size[1]
    )


def crop_windows(image: Image.Image, face: Box | None) -> list[tuple[int, int]]:
    """Possible (left, top) of the 3:4 window; the first one is the default."""

    w, h = image.size
    cw, ch = _window(image)
    if not face:
        return [((w - cw) // 2, (h - ch) // 2)]
    cx, cy = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
    options: list[tuple[int, int]] = []
    # Face a little above centre reads best; the rest trade headroom for title room.
    for ax, ay in (
        (0.5, 0.42),
        (0.5, 0.30),
        (0.5, 0.58),
        (0.5, 0.0),
        (0.5, 1.0),
        (0.30, 0.42),
        (0.70, 0.42),
    ):
        left = min(max(0, round(cx - cw * ax)), w - cw)
        top = min(max(0, round(cy - ch * ay)), h - ch)
        if (left, top) not in options:
            options.append((left, top))
    return options


def crop_to_canvas(
    image: Image.Image, face: Box | None, text: str | None = None
) -> tuple[Image.Image, Box | None]:
    """A 3:4 window around the face, scaled to 1080x1440.

    With ``text``, the window slides within the source (a 9:16 frame has 480 px
    of play) to where the title fits biggest around the face.
    """

    cw, ch = _window(image)
    windows = crop_windows(image, face)
    left, top = windows[0]
    if text and face and len(windows) > 1:
        best = -1
        for option in windows:
            moved = _crop_face(face, option[0], option[1], cw, ch)
            if not _whole_face(face, option, (cw, ch)):
                continue  # never trade a cut-off face for title room
            sizes = [
                fit.size
                for layout in choose_layouts(moved, text=text)
                if (fit := fit_text(text, text_zone(layout, moved), layout))
            ]
            score = max(sizes, default=0)
            if score > best:
                best, (left, top) = score, option
    cropped = image.crop((left, top, left + cw, top + ch)).resize(
        CANVAS, Image.Resampling.LANCZOS
    )
    return cropped, _crop_face(face, left, top, cw, ch)


def warm_grade(image: Image.Image) -> Image.Image:
    """Gentle warm tone and lift for the real-frame background; no face redraw."""

    rgb = image.convert("RGB")
    r, g, b = rgb.split()
    r = r.point(lambda v: min(255, round(v * 1.04 + 3)))
    g = g.point(lambda v: min(255, round(v * 1.01 + 2)))
    b = b.point(lambda v: round(v * 0.95))
    graded = Image.merge("RGB", (r, g, b))
    mean = ImageStat.Stat(graded.convert("L")).mean[0]
    if mean < 110:
        lift = min(1.18, 110 / max(mean, 1))
        graded = graded.point(lambda v: min(255, round(v * lift)))
    return graded


# ------------------------------------------------------------------- layouts


def choose_layouts(
    face: Box | None, previous: tuple[str, ...] = (), text: str | None = None
) -> list[Layout]:
    """Layouts in preference order for a face position (references/layouts.md).

    With ``text``, only layouts whose zone (after stepping away from the face)
    can hold the title are kept; layouts used by the previous batch go last.
    Candidate ``n`` starts from entry ``n``, so two candidates differ whenever
    two layouts fit.
    """

    order: list[Layout]
    if face is None:
        order = ["center", "top", "bottom"]
    else:
        cx = (face[0] + face[2]) / 2 / CANVAS[0]
        cy = (face[1] + face[3]) / 2 / CANVAS[1]
        vertical: list[Layout] = ["top", "bottom"] if cy > 0.42 else ["bottom", "top"]
        side_first = cx < 0.38 or cx > 0.62
        order = ["side", *vertical] if side_first else [*vertical, "side"]
    if text is not None:
        fitting = [x for x in order if fit_text(text, text_zone(x, face), x)]
        order = fitting or order
    fresh = [x for x in order if x not in previous]
    return fresh + [x for x in order if x in previous]


def text_zone(layout: Layout, face: Box | None) -> Box:
    """The title zone in pixels, shrunk away from the face's safety box."""

    if layout == "side":
        on_right = face is not None and (face[0] + face[2]) / 2 > CANVAS[0] / 2
        zone = _px(ZONES["side_left" if on_right else "side_right"], CANVAS)
    else:
        zone = _px(ZONES[layout], CANVAS)
    block = forbidden_zone(face)
    if block is None or intersection(zone, block) == 0:
        return zone
    x0, y0, x1, y1 = zone
    margin = 24
    if layout == "top":
        y1 = min(y1, block[1] - margin)
    elif layout == "bottom":
        y0 = max(y0, block[3] + margin)
    elif layout == "side":
        if block[0] >= (x0 + x1) / 2:
            x1 = min(x1, block[0] - margin)
        else:
            x0 = max(x0, block[2] + margin)
    else:
        if block[1] > (y0 + y1) / 2:
            y1 = min(y1, block[1] - margin)
        else:
            y0 = max(y0, block[3] + margin)
    return (x0, y0, max(x0, x1), max(y0, y1))


# ------------------------------------------------------------------ text fit


BREAK_AFTER = set("，。！？；：、,.!?;:")


_WORDS_LOCK = threading.Lock()
_WORDS: list[Any] = []


def _word_tokenizer() -> Any:
    """The caption module's pinned jieba dictionary, or None (then per character).

    Loaded once per process under a lock: two covers must not build it at once.
    """

    if _WORDS:
        return _WORDS[0]
    with _WORDS_LOCK:
        if not _WORDS:
            try:
                from .video_editing_captioning import tokenizer

                _WORDS.append(tokenizer())
            except Exception:
                _WORDS.append(None)
    return _WORDS[0]


def _is_latin(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in ".%")


def _units(text: str) -> list[str]:
    """Break units: jieba words when available, else one CJK character; latin
    letters and digits always stay together."""

    engine = _word_tokenizer()
    pieces = list(engine.cut(text, HMM=False)) if engine is not None else list(text)
    units: list[str] = []
    for piece in pieces:
        if units and piece and _is_latin(piece[0]) and _is_latin(units[-1][-1]):
            units[-1] += piece
        else:
            units.append(piece)
    return [unit for unit in units if unit]


def break_lines(text: str, lines: int) -> list[str] | None:
    """Split into ``lines`` lines: even lengths, words kept whole, breaks after
    punctuation preferred, 避头尾 punctuation respected."""

    units = _units(text)
    if lines <= 1 or len(units) <= 1:
        return [text]
    if lines > len(units):
        return None
    total = len(text)
    cuts: list[int] = []
    position, consumed = 0, 0
    for line in range(1, lines):
        goal = total * line / lines
        best, best_cost = None, None
        for index in range(position + 1, len(units) - (lines - 1 - line)):
            length = consumed + sum(len(u) for u in units[position:index])
            head, tail = units[index], units[index - 1]
            if (
                head[0] in NO_LINE_START
                or head[0] in PARTICLES
                or tail[-1] in NO_LINE_END
                or head == " "
            ):
                continue
            cost = abs(length - goal) - (2.5 if tail[-1] in BREAK_AFTER else 0)
            if best_cost is None or cost < best_cost:
                best, best_cost = index, cost
        if best is None:
            return None
        consumed += sum(len(u) for u in units[position:best])
        cuts.append(best)
        position = best
    pieces = []
    start = 0
    for cut in [*cuts, len(units)]:
        piece = "".join(units[start:cut]).strip()
        if not piece:
            return None
        pieces.append(piece)
        start = cut
    return pieces


@lru_cache(maxsize=32)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


@lru_cache(maxsize=4096)
def has_glyph(ch: str) -> bool:
    """A character renders as itself, not as the font's .notdef box."""

    if ch.isspace():
        return True
    return _glyph_bitmap(ch) != _glyph_bitmap("\U0010fffd")


@lru_cache(maxsize=4096)
def _glyph_bitmap(ch: str) -> bytes:
    canvas = Image.new("L", (96, 96))
    ImageDraw.Draw(canvas).text((12, 4), ch, font=font(64), fill=255)
    return canvas.tobytes()


def missing_glyphs(text: str) -> list[str]:
    return sorted({ch for ch in text if not has_glyph(ch)})


def normalise_cover_text(text: str) -> str:
    return " ".join(text.replace("　", " ").split())


def default_cover_text(title: str) -> str:
    """Publish title without topic tags or characters the font cannot draw (emoji)."""

    words = [w for w in title.replace("　", " ").split() if not w.startswith("#")]
    kept = "".join(ch for ch in " ".join(words) if has_glyph(ch))
    return normalise_cover_text(kept)[:MAX_TEXT_CHARS]


def line_width(text: str, size: int) -> int:
    left, _, right, _ = font(size).getbbox(text)
    return round(right - left)


@dataclass
class Fit:
    lines: list[str]
    size: int


def fit_text(text: str, zone: Box, layout: Layout) -> Fit | None:
    width, height = zone[2] - zone[0], zone[3] - zone[1]
    best: Fit | None = None
    for count in range(1, MAX_LINES[layout] + 1):
        lines = break_lines(text, count)
        if not lines:
            continue
        size = min(round(height / (count * LINE_GAP)), 168)
        while (
            size >= MIN_FONT and max(line_width(line, size) for line in lines) > width
        ):
            size -= 4
        if size < MIN_FONT:
            continue
        # Prefer fewer lines unless more lines buy a clearly bigger title.
        if best is None or size > best.size * 1.12:
            best = Fit(lines, size)
    return best


# ------------------------------------------------------------------- render


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def is_blue_purple(rgb: tuple[int, int, int], min_saturation: float = 0.2) -> bool:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return 200 <= h * 360 <= 290 and s > min_saturation and v > 0.2


@dataclass
class Typeset:
    image: Image.Image
    layout: Layout
    zone: Box
    lines: list[str]
    font_size: int
    text_boxes: list[Box]
    design_colors: list[str]
    plate: Box | None
    tone: Literal["dark", "light"]


def typeset(
    background: Image.Image,
    text: str,
    layout: Layout,
    face: Box | None,
    highlight: str | None = None,
) -> Typeset:
    if background.size != CANVAS:
        background = background.resize(CANVAS, Image.Resampling.LANCZOS)
    zone = text_zone(layout, face)
    fit = fit_text(text, zone, layout)
    if fit is None:
        raise CoverComposeError(
            "COVER_TEXT_DOES_NOT_FIT", "封面大字太长，放不下，请删减几个字。"
        )
    size = fit.size
    face_ = font(size)
    line_height = round(size * LINE_GAP)
    block_h = line_height * len(fit.lines)
    top = zone[1] + max(0, (zone[3] - zone[1] - block_h) // 2)
    align_left = layout == "side"

    region = background.convert("L").crop(zone)
    stat = ImageStat.Stat(region)
    luminance = stat.mean[0] / 255
    busy = math.sqrt(stat.var[0]) / 255 > 0.18
    tone: Literal["dark", "light"] = "dark" if luminance > 0.55 else "light"
    text_color = DARK_TEXT if tone == "dark" else LIGHT_TEXT
    accent = HIGHLIGHT_ON_DARK_TEXT if tone == "dark" else HIGHLIGHT_ON_LIGHT_TEXT
    used = [text_color]

    positions: list[tuple[int, int, str]] = []
    boxes: list[Box] = []
    for index, line in enumerate(fit.lines):
        width = line_width(line, size)
        x = zone[0] if align_left else zone[0] + (zone[2] - zone[0] - width) // 2
        y = top + index * line_height
        left, top_, right, bottom = (round(v) for v in face_.getbbox(line))
        positions.append((x - left, y, line))
        boxes.append((x, y + top_, x + (right - left), y + bottom))

    canvas = background.convert("RGBA")
    plate: Box | None = None
    if busy:
        pad = round(size * 0.32)
        plate = (
            max(0, min(b[0] for b in boxes) - pad),
            max(0, min(b[1] for b in boxes) - pad),
            min(CANVAS[0], max(b[2] for b in boxes) + pad),
            min(CANVAS[1], max(b[3] for b in boxes) + pad),
        )
        fill = PLATE_LIGHT if tone == "dark" else PLATE_DARK
        layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            plate, radius=round(size * 0.28), fill=fill
        )
        canvas = Image.alpha_composite(canvas, layer)
        used.append("#{:02X}{:02X}{:02X}".format(*fill[:3]))

    if tone == "light":
        shadow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shadow)
        offset = max(2, size // 28)
        for x, y, line in positions:
            draw.text(
                (x + offset, y + offset),
                line,
                font=face_,
                fill=hex_rgb(SHADOW) + (170,),
            )
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, size // 18)))
        canvas = Image.alpha_composite(canvas, shadow)
        used.append(SHADOW)

    draw = ImageDraw.Draw(canvas)
    marked = _highlight_mask(text, fit.lines, highlight)
    stroke = max(2, size // 22) if tone == "dark" else 0
    if stroke:
        used.append(OUTLINE_LIGHT)
    if any(any(m) for m in marked):
        used.append(accent)
    for (x, y, line), flags in zip(positions, marked, strict=True):
        cursor = x
        for ch, on in zip(line, flags, strict=True):
            draw.text(
                (cursor, y),
                ch,
                font=face_,
                fill=accent if on else text_color,
                stroke_width=stroke,
                stroke_fill=OUTLINE_LIGHT if stroke else None,
            )
            cursor += round(face_.getlength(ch))
    return Typeset(
        canvas.convert("RGB"), layout, zone, fit.lines, size, boxes, used, plate, tone
    )


def _highlight_mask(
    text: str, lines: list[str], highlight: str | None
) -> list[list[bool]]:
    flat = "".join(lines)
    flags = [False] * len(flat)
    if highlight and highlight in flat:
        start = flat.index(highlight)
        for i in range(start, start + len(highlight)):
            flags[i] = True
    out, index = [], 0
    for line in lines:
        out.append(flags[index : index + len(line)])
        index += len(line)
    return out


# -------------------------------------------------------------------- checks


def picture_cool_share(image: Image.Image, face: Box | None) -> float:
    """Saturated blue/purple share outside the presenter box (lenient, hint only)."""

    small = image.convert("RGB").resize((108, 144))
    ignore = presenter_zone(face)
    scale = 108 / CANVAS[0]
    skip = tuple(round(v * scale) for v in ignore) if ignore else None
    counted = cool = 0
    data = list(small.getdata())
    for y in range(144):
        for x in range(108):
            if skip and skip[0] <= x < skip[2] and skip[1] <= y < skip[3]:
                continue
            counted += 1
            if is_blue_purple(data[y * 108 + x], 0.35):
                cool += 1
    return round(cool / counted, 4) if counted else 0.0


@dataclass
class Checks:
    text_exact: bool
    glyphs_ok: bool
    missing_glyphs: list[str]
    face_clear: bool
    face_overlap_px: int
    design_colors_ok: bool
    size_ok: bool
    picture_cool_share: float
    picture_cool_hint: bool
    face_detected: bool
    passed: bool = field(init=False)

    def __post_init__(self) -> None:
        self.passed = all(
            (
                self.text_exact,
                self.glyphs_ok,
                self.face_clear,
                self.design_colors_ok,
                self.size_ok,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify(result: Typeset, text: str, face: Box | None) -> Checks:
    joined = "".join(result.lines).replace(" ", "")
    missing = missing_glyphs(text)
    block = forbidden_zone(face)
    overlap = sum(intersection(box, block) for box in result.text_boxes) if block else 0
    if block and result.plate:
        overlap += intersection(result.plate, block)
    share = picture_cool_share(result.image, face)
    return Checks(
        text_exact=joined == text.replace(" ", ""),
        glyphs_ok=not missing,
        missing_glyphs=missing,
        face_clear=overlap == 0,
        face_overlap_px=overlap,
        design_colors_ok=not any(
            is_blue_purple(hex_rgb(c)) for c in result.design_colors
        ),
        size_ok=result.image.size == CANVAS,
        picture_cool_share=share,
        picture_cool_hint=share > PICTURE_COOL_HINT,
        face_detected=face is not None,
    )


def compose(
    background: Image.Image,
    text: str,
    layouts: list[Layout],
    face: Box | None,
    highlight: str | None = None,
) -> tuple[Typeset, Checks]:
    """First layout whose typeset passes every check; raises when none does."""

    last: CoverComposeError | None = None
    for layout in layouts:
        try:
            result = typeset(background, text, layout, face, highlight)
        except CoverComposeError as exc:
            last = exc
            continue
        checks = verify(result, text, face)
        if checks.passed:
            return result, checks
        last = CoverComposeError("COVER_CHECK_FAILED", "封面核对没有通过。")
    raise last or CoverComposeError("COVER_CHECK_FAILED", "封面核对没有通过。")


def save_views(result: Image.Image, face: Box | None, root: Path) -> dict[str, str]:
    """cover.jpg plus the review views: 200 px thumbnail and the 100% face crop."""

    root.mkdir(parents=True, exist_ok=True)
    paths = {"cover": root / "cover.jpg", "thumb": root / "thumb.jpg"}
    result.save(paths["cover"], "JPEG", quality=92, optimize=True)
    result.resize((360, 480), Image.Resampling.LANCZOS).save(
        paths["thumb"], "JPEG", quality=88
    )
    if face:
        block = forbidden_zone(face) or face
        paths["face"] = root / "face.jpg"
        result.crop(block).save(paths["face"], "JPEG", quality=90)
    return {key: str(value) for key, value in paths.items()}


POSTER_SIZE = (480, 640)
_POSTER_SLOTS = threading.BoundedSemaphore(2)


def make_poster(video: Path, target: Path, at: float = 0.5) -> Path:
    """A 3:4 grid thumbnail (480x640 JPEG) from one early frame, face-centred.

    At most two run at once per process, so a grid of 40 works never starts 40
    ffmpeg processes; the result is cached by the caller at ``target``.
    """

    with _POSTER_SLOTS:
        target.parent.mkdir(parents=True, exist_ok=True)
        frame_path = target.with_suffix(".frame.jpg")
        try:
            duration = probe_duration(video)
            extract_frame(video, min(at, max(0.0, duration / 2)), frame_path)
            with Image.open(frame_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        finally:
            frame_path.unlink(missing_ok=True)
        found = detect_face(image)
        cropped, _ = crop_to_canvas(image, found[0] if found else None)
        partial = target.with_suffix(".part.jpg")
        cropped.resize(POSTER_SIZE, Image.Resampling.LANCZOS).save(
            partial, "JPEG", quality=82, optimize=True
        )
        partial.replace(target)
        return target
