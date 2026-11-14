"""V03: editable media-window takeover and thumbnail queue, no presenter/text.

Public interface returns independent RGBA slots. All clocks are local frames.
Observed transforms are approximate; source media clocks are explicit and muted.
"""

from __future__ import annotations

import atexit
import io
from pathlib import Path
from typing import Any, TypedDict

import cv2
from PIL import Image, ImageDraw, ImageFilter


class _ReaderState(TypedDict):
    cap: Any
    index: int
    image: Image.Image | None
    fps: float
    frames: int


_READERS: dict[str, _ReaderState] = {}
_IMAGES: dict[str, Image.Image] = {}


def clear_cache() -> None:
    for item in _READERS.values():
        item["cap"].release()
    _READERS.clear()
    _IMAGES.clear()


atexit.register(clear_cache)


def _out(a: float, b: float, t: float) -> float:
    x = max(0.0, min(1.0, (t - a) / (b - a))) if b > a else float(t >= b)
    return 1 - (1 - x) ** 3


def _mix(a: float, b: float, q: float) -> float:
    return a + (b - a) * q


def _sample(entry: dict[str, Any], frame: int, fps: float) -> Image.Image | None:
    path = str(Path(entry["path"]).resolve())
    kind = entry.get("type", "auto")
    if kind == "auto":
        kind = (
            "image"
            if Path(path).suffix.lower()
            in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg"}
            else "video"
        )
    if kind == "image":
        if path not in _IMAGES:
            if Path(path).suffix.lower() == ".svg":
                try:
                    import cairosvg
                except ImportError as ex:
                    raise ValueError("SVG input requires cairosvg") from ex
                image = Image.open(io.BytesIO(cairosvg.svg2png(url=path))).convert(
                    "RGBA"
                )
            else:
                image = Image.open(path).convert("RGBA")
            _IMAGES[path] = image
        return _IMAGES[path]
    if kind != "video":
        raise ValueError("Media input type must be auto, image or video")
    if path not in _READERS:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise ValueError(f"Cannot decode media: {path}")
        _READERS[path] = {
            "cap": cap,
            "index": -1,
            "image": None,
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "frames": round(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
    item = _READERS[path]
    if item["fps"] <= 0 or item["frames"] <= 0:
        raise ValueError("Media needs a positive frame clock")
    time = entry.get("source_in", 0) + max(
        0.0, (frame - entry["start_frame"]) / fps
    ) * entry.get("speed", 1)
    source_out = entry.get("source_out", (item["frames"] - 1) / item["fps"])
    if time > source_out:
        policy = entry.get("end_policy", "error")
        if policy == "hold":
            time = source_out
        elif policy == "transparent":
            return None
        elif policy == "loop":
            time = entry.get("source_in", 0) + (time - entry.get("source_in", 0)) % (
                source_out - entry.get("source_in", 0)
            )
        else:
            raise ValueError("Media ended before its planned window")
    index = min(item["frames"] - 1, max(0, round(time * item["fps"])))
    if index != item["index"]:
        if not (item["index"] < index <= item["index"] + 5):
            item["cap"].set(cv2.CAP_PROP_POS_FRAMES, index)
        else:
            for _ in range(index - item["index"] - 1):
                item["cap"].grab()
        ok, bgr = item["cap"].read()
        if not ok:
            raise ValueError("Planned source frame cannot be decoded")
        item["image"] = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
        item["index"] = index
    return item["image"]


def _fit(image: Image.Image, w: int, h: int, entry: dict[str, Any]) -> Image.Image:
    crop = entry.get("crop")
    if crop:
        if (
            len(crop) != 4
            or not 0 <= crop[0] < crop[2] <= 1
            or not 0 <= crop[1] < crop[3] <= 1
        ):
            raise ValueError("crop must be a normalized source rectangle")
        image = image.crop(
            tuple(
                round(v * (image.width if i % 2 == 0 else image.height))
                for i, v in enumerate(crop)
            )
        )
    fit = entry.get("fit", "cover")
    if fit == "stretch":
        return image.resize((w, h), Image.Resampling.LANCZOS)
    if fit not in {"cover", "contain"}:
        raise ValueError("Unknown media fit")
    scale = (max if fit == "cover" else min)(w / image.width, h / image.height)
    im = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    anchor = entry.get("anchor", [0.5, 0.5])
    x = round((w - im.width) * anchor[0])
    y = round((h - im.height) * anchor[1])
    result = Image.new("RGBA", (w, h))
    result.alpha_composite(im, (x, y))
    return result


def render(
    component_id: str,
    raw_frame: Image.Image | None,
    local_frame: int,
    inputs: dict[str, Any],
    disabled: bool = False,
) -> dict[str, Image.Image]:
    if component_id != "V03":
        raise ValueError("apple_media only owns V03")
    W, H = map(int, inputs.get("size", [1080, 1920]))
    fps = float(inputs.get("fps", 25))
    k = W / 540
    if abs(H - 960 * k) > 1 or fps <= 0:
        raise ValueError(
            "V03 measured layout supports 9:16 with a positive frame clock"
        )
    entries = inputs.get("media_entries", [])
    roles = {f"media-{e['id']}": Image.new("RGBA", (W, H)) for e in entries}
    if disabled:
        return roles
    for entry in entries:
        start = entry["start_frame"]
        if local_frame < start:
            continue
        rect = entry["rect"]
        opacity = 1.0
        blur = 0.0
        demote = entry.get("demote_frame")
        if demote is not None and local_frame >= demote:
            q = _out(demote, demote + entry.get("demote_frames", 13), local_frame)
            rect = [
                _mix(a, b, q)
                for a, b in zip(rect, entry["thumbnail_rect"], strict=True)
            ]
        entry_frames = entry.get("entry_frames", 8)
        if entry_frames > 0 and local_frame < start + entry_frames:
            q = _out(start, start + entry_frames, local_frame)
            opacity = q
            blur = (1 - q) * entry.get("entry_blur", 10) * k
        material = _sample(entry, local_frame, fps)
        if material is None:
            continue
        x, y, x2, y2 = [round(v * k) for v in rect]
        w = max(1, x2 - x)
        h = max(1, y2 - y)
        im = _fit(material, w, h, entry)
        radius = entry.get("radius", 14) * k
        if radius:
            mask = Image.new("L", (w, h))
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, w - 1, h - 1), radius=radius, fill=255
            )
            original = im.getchannel("A")
            im.putalpha(
                Image.fromarray(
                    cv2.multiply(
                        __import__("numpy").asarray(original),
                        __import__("numpy").asarray(mask),
                        scale=1 / 255,
                    )
                )
            )
        if blur > 0:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        if opacity < 1:
            im.putalpha(
                im.getchannel("A").point(lambda a, opacity=opacity: round(a * opacity))
            )
        roles[f"media-{entry['id']}"].alpha_composite(im, (x, y))
    exit_ = inputs.get("exit")
    if exit_ and local_frame >= exit_["start_frame"]:
        q = _out(exit_["start_frame"], exit_["end_frame"], local_frame)
        scale = _mix(1, exit_.get("scale", 1.12), q)
        anchor = exit_.get("anchor", [270, 340])
        dx = round(anchor[0] * k * (1 - scale))
        dy = round(anchor[1] * k * (1 - scale))
        for key, layer in roles.items():
            transformed = Image.new("RGBA", (W, H))
            transformed.alpha_composite(
                layer.resize(
                    (round(W * scale), round(H * scale)), Image.Resampling.BICUBIC
                ),
                (dx, dy),
            )
            if q > 0:
                transformed = transformed.filter(
                    ImageFilter.GaussianBlur(q * exit_.get("blur", 4) * k)
                )
                transformed.putalpha(
                    transformed.getchannel("A").point(lambda a: round(a * (1 - q)))
                )
            roles[key] = transformed
    return roles
