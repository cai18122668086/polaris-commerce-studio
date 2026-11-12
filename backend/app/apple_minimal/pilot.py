"""Editable reference reconstruction: raw moving presenter + independent RGBA roles.
No source reference video is sampled by this renderer. All geometry is parameterized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BYTES = Path(__file__).read_bytes()
SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()


def ease(a: float, b: float, t: float) -> float:
    x = max(0.0, min(1.0, (t - a) / (b - a))) if b > a else float(t >= b)
    return x * x * (3 - 2 * x)


def blend(a: float, b: float, q: float) -> float:
    return a + (b - a) * q


def digest(p: str | Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def box(alpha: Image.Image) -> list[int] | None:
    bounds = alpha.getbbox()
    return list(bounds) if bounds is not None else None


@lru_cache(maxsize=80)
def font(path: str | Path, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, round(size))


def text_image(
    text: str,
    path: str | Path,
    size: float,
    fill: Any,
    stroke: int = 0,
    stroke_fill: Any = (30, 30, 30, 200),
    shadow: Any = None,
) -> tuple[Image.Image, tuple[int, int, int, int], int]:
    f = font(path, size)
    b = cast(
        tuple[int, int, int, int], f.getbbox(text, anchor="ls", stroke_width=stroke)
    )
    pad = 16
    im = Image.new("RGBA", (b[2] - b[0] + 2 * pad, b[3] - b[1] + 2 * pad))
    d = ImageDraw.Draw(im)
    d.text(
        (pad - b[0], pad - b[1]),
        text,
        font=f,
        fill=fill,
        anchor="ls",
        stroke_width=stroke,
        stroke_fill=stroke_fill,
    )
    return im, b, pad


def place_center(
    layer: Image.Image,
    im: Image.Image,
    cx: float,
    top: float,
    opacity: float = 1,
    scale: float = 1,
    blur: float = 0,
) -> None:
    if opacity <= 0:
        return
    if scale != 1:
        im = im.resize(
            (max(1, round(im.width * scale)), max(1, round(im.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if opacity < 1:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda a: round(a * opacity)))
    layer.alpha_composite(im, (round(cx - im.width / 2), round(top)))


class Suite:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.W, self.H = cfg.get("size", [1080, 1920])
        self.k = self.W / 540
        self.fonts = cfg["fonts"]
        self.registration = cfg["registration"]
        self.ui = Image.open(cfg["ui_image"]).convert("RGBA")
        self.media_capture = (
            cv2.VideoCapture(cfg["media_source"]) if cfg.get("media_source") else None
        )
        self.media_index = -1
        self.media_frame: Image.Image | None = None
        if self.media_capture is not None and not self.media_capture.isOpened():
            raise ValueError("Original material video cannot be decoded")
        self.static: dict[str, tuple[Image.Image, tuple[int, int, int, int], int]] = {}

    def blank(self) -> Image.Image:
        return Image.new("RGBA", (self.W, self.H))

    def txt(
        self,
        key: str,
        text: str,
        path: str | Path,
        size: float,
        fill: Any,
        stroke: int = 0,
        stroke_fill: Any = (30, 30, 30, 200),
    ) -> tuple[Image.Image, tuple[int, int, int, int], int]:
        if key not in self.static:
            self.static[key] = text_image(text, path, size, fill, stroke, stroke_fill)
        return self.static[key]

    def matrix(self, t: float) -> np.ndarray:
        points = self.registration
        if t <= points[0]["time"]:
            return np.array(points[0]["matrix_540"], np.float32)
        for a, b in zip(points, points[1:], strict=False):
            if a["time"] <= t <= b["time"]:
                q = (t - a["time"]) / (b["time"] - a["time"])
                return (
                    np.array(a["matrix_540"], np.float32) * (1 - q)
                    + np.array(b["matrix_540"], np.float32) * q
                )
        return np.array(points[-1]["matrix_540"], np.float32)

    def render_visual(
        self, raw: Image.Image, t: float, media_time: float | None = None
    ) -> dict[str, Image.Image]:
        k = self.k
        matrix = self.matrix(t)
        matrix[:, 2] *= k
        shifted = cv2.warpAffine(
            np.array(raw),
            matrix,
            (self.W, self.H),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
        )
        q = ease(10.32, 10.72, t)
        crop = [
            38 * k * q,
            117 * k * q,
            self.W - 38 * k * q,
            self.H - (960 - 741) * k * q,
        ]
        mask = Image.new("L", (self.W, self.H))
        ImageDraw.Draw(mask).rounded_rectangle(tuple(crop), radius=70 * k * q, fill=255)
        alpha = cv2.warpAffine(
            np.asarray(mask),
            matrix,
            (self.W, self.H),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        person = Image.fromarray(shifted).convert("RGBA")
        person.putalpha(Image.fromarray(alpha))
        background = Image.new(
            "RGBA", (self.W, self.H), tuple(self.cfg["stage_color"]) + (255,)
        )
        bg = raw.filter(ImageFilter.GaussianBlur(20 * k)).convert("RGBA")
        background.alpha_composite(
            bg if t < 10.32 else Image.blend(background, bg, 1 - ease(10.32, 10.6, t))
        )
        media = self.blank()
        appear = ease(10.84, 11.2, t)
        if appear > 0:
            w = round(blend(0.86, 1, appear) * 996 * k / 2)
            h = round(w * 978 / 996)
            material = self.ui
            if self.media_capture is not None:
                output_entry = 10.84
                asset_time = max(
                    0, (t if media_time is None else media_time) - output_entry
                ) + self.cfg.get("media_in", 0)
                index = round(asset_time * self.media_capture.get(cv2.CAP_PROP_FPS))
                total = round(self.media_capture.get(cv2.CAP_PROP_FRAME_COUNT))
                if index >= total:
                    raise ValueError(
                        "Original material video does not cover the planned occurrence"
                    )
                if index != self.media_index:
                    self.media_capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                    ok, frame = self.media_capture.read()
                    if not ok:
                        raise ValueError("Material frame cannot be decoded")
                    self.media_frame = Image.fromarray(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    ).convert("RGBA")
                    self.media_index = index
            assert self.media_frame is not None
            material = self.media_frame
            fit = max(w / material.width, h / material.height)
            image = material.resize(
                (round(material.width * fit), round(material.height * fit)),
                Image.Resampling.LANCZOS,
            )
            left = (image.width - w) // 2
            top = (image.height - h) // 2
            image = image.crop((left, top, left + w, top + h))
            if appear < 1:
                image = image.filter(ImageFilter.GaussianBlur((1 - appear) * 12 * k))
                image.putalpha(image.getchannel("A").point(lambda a: round(a * appear)))
            media.alpha_composite(
                image, (round(self.W / 2 - w / 2), round((93 + (1 - appear) * 34) * k))
            )
        return {"background": background, "presenter": person, "media": media}

    def render_subtitle(
        self, t: float, caption_time: float | None = None
    ) -> dict[str, Image.Image]:
        k = self.k
        cfg = self.cfg
        roles = {
            x: self.blank()
            for x in ["wash", "support", "main", "chapter", "caption", "border"]
        }
        enter = 1 if t == 0 else ease(0.28, 0.64, t)
        wash = enter * (1 - ease(9.64, 10.16, t))
        if t == 0:
            wash = 1
        if wash > 0:
            y = np.arange(self.H)[:, None] / k
            gradient = np.clip((475 - y) / (475 - 275), 0, 1) * 255 * wash
            gradient = np.repeat(gradient, self.W, axis=1).astype(np.uint8)
            im = Image.new("RGBA", (self.W, self.H), tuple(cfg["opening_color"]) + (0,))
            im.putalpha(Image.fromarray(gradient))
            roles["wash"] = im
        end = 1 - ease(9.64, 10.08, t)
        support = enter * end
        if t == 0:
            support = 1
        if support > 0:
            im, b, pad = self.txt(
                "support",
                cfg["support"],
                self.fonts["support"],
                64 * k / 2,
                (8, 8, 8, 255),
            )
            top = (113.5 + blend(52, 0, enter) + 180 * ease(9.64, 10.08, t)) * k - pad
            place_center(
                roles["support"],
                im,
                self.W / 2,
                top,
                support,
                blur=5 * k * (1 - enter) + 6 * k * (1 - end),
            )
        title = ease(0.96, 1.4, t) * end
        if title > 0:
            im, b, pad = self.txt(
                "main",
                cfg["main"],
                self.fonts["main"],
                149 * k / 2,
                (255, 255, 255, 255),
            )
            mask = im.getchannel("A")
            colors = np.zeros((im.height, im.width, 4), np.uint8)
            left = np.array([13, 77, 118])
            right = np.array([73, 73, 76])
            colors[:, :, :3] = (
                left[None, None, :] * (1 - np.linspace(0, 1, im.width)[None, :, None])
                + right[None, None, :] * np.linspace(0, 1, im.width)[None, :, None]
            ).astype(np.uint8)
            colors[:, :, 3] = np.asarray(mask)
            im = Image.fromarray(colors)
            q = ease(0.96, 1.4, t)
            place_center(
                roles["main"],
                im,
                self.W / 2,
                (167.5 + 100 * ease(9.64, 10.08, t)) * k - pad,
                title,
                scale=blend(0.92, 1, q),
                blur=(1 - q) * 8 * k + (1 - end) * 7 * k,
            )
        cap = ease(5.08, 5.4, t)
        if cap > 0:
            label = cfg["chapters"][0] if t < 7.6 else cfg["chapters"][-1]
            f = font(self.fonts["main"], 16 * k)
            length = f.getlength(label)
            w = round(length + 62 * k)
            h = 42 * k
            im = Image.new("RGBA", (w + 40 * round(k), round(h + 40 * k)))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle(
                (20 * k, 20 * k, w + 20 * k, h + 20 * k),
                radius=21 * k,
                fill=(255, 255, 255, 245),
            )
            shadow = im.getchannel("A").filter(ImageFilter.GaussianBlur(9 * k))
            sh = Image.new("RGBA", im.size, (60, 40, 60, 0))
            sh.putalpha(shadow.point(lambda a: round(a * 0.10)))
            sh.alpha_composite(im)
            im = sh
            d = ImageDraw.Draw(im)
            d.ellipse((31 * k, 31 * k, 51 * k, 51 * k), fill=(0, 119, 214, 255))
            d.ellipse((36 * k, 36 * k, 46 * k, 46 * k), fill="white")
            d.text((60 * k, 29 * k), label, font=f, fill=(10, 10, 10, 255), anchor="lt")
            place_center(
                roles["chapter"], im, self.W / 2, 12 * k, cap, scale=blend(0.94, 1, cap)
            )
        ct = t if caption_time is None else caption_time
        if t == 0:
            ct = cfg["captions"][0]["time"][0] + 0.18
        for row in cfg["captions"]:
            a, b = row["time"]
            if not a <= ct < b:
                continue
            progress = ease(a, a + 0.18, ct) * (1 - ease(b - 0.10, b, ct))
            phase = t >= 10.32
            body_size = (30 if phase else 28) * k
            accent_size = 35 * k
            accent = row.get("emphasis", "") if not phase else ""
            text = row["text"]
            pos = text.find(accent) if accent else -1
            parts = (
                [
                    (text[:pos], False),
                    (accent, True),
                    (text[pos + len(accent) :], False),
                ]
                if pos >= 0
                else [(text, False)]
            )
            text_layer = self.blank()
            length = sum(
                font(
                    self.fonts["caption_bold"] if emph else self.fonts["caption"],
                    accent_size if emph else body_size,
                ).getlength(s)
                for s, emph in parts
            )
            x = (self.W - length) / 2
            baseline = 834 * k
            for part, emph in parts:
                if not part:
                    continue
                path = self.fonts["caption_bold"] if emph else self.fonts["caption"]
                size = accent_size if emph else body_size
                f = font(path, size)
                draw = ImageDraw.Draw(text_layer)
                fill = (
                    (0, 151, 233, 255)
                    if emph
                    else (12, 12, 12, 255)
                    if phase
                    else (255, 255, 255, 255)
                )
                stroke = (255, 255, 255, 210) if phase else (25, 25, 25, 170)
                draw.text(
                    (round(x), round(baseline)),
                    part,
                    font=f,
                    fill=fill,
                    anchor="ls",
                    stroke_width=max(1, round(k)),
                    stroke_fill=stroke,
                )
                x += f.getlength(part)
            shadow = text_layer.getchannel("A").filter(ImageFilter.GaussianBlur(2 * k))
            sh = self.blank()
            sh.paste(
                (255, 255, 255, 0) if phase else (10, 15, 20, 0), (0, 0, self.W, self.H)
            )
            sh.putalpha(shadow.point(lambda v: round(v * 0.55)))
            sh.alpha_composite(text_layer)
            scale = blend(0.94, 1, ease(a, a + 0.18, ct))
            im = sh
            if scale != 1:
                small = im.resize(
                    (round(self.W * scale), round(self.H * scale)),
                    Image.Resampling.LANCZOS,
                )
                im = self.blank()
                im.alpha_composite(
                    small,
                    (
                        round((self.W - small.width) / 2),
                        round((self.H - small.height) * 0.86),
                    ),
                )
            if progress < 1:
                im = im.filter(ImageFilter.GaussianBlur((1 - progress) * 3 * k))
                im.putalpha(
                    im.getchannel("A").point(
                        lambda v, progress=progress: round(v * progress)
                    )
                )
            roles["caption"] = im
        opacity = ease(0.76, 1.02, t) * (1 - ease(2.7, 3.7, t))
        if opacity > 0:
            d = ImageDraw.Draw(roles["border"])
            d.rounded_rectangle(
                (3 * k, 3 * k, self.W - 3 * k, self.H - 3 * k),
                radius=25 * k,
                outline=(35, 132, 199, round(220 * opacity)),
                width=max(1, round(5 * k)),
            )
        return roles


def render(cfg: dict[str, Any], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=False)
    (out / "source-snapshot.py").write_bytes(SOURCE_BYTES)
    (out / "input-snapshot.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf8"
    )
    W, H = cfg.get("size", [1080, 1920])
    fps = cfg.get("fps", 25)
    frames = round(cfg["duration"] * fps)
    suite = Suite(cfg)
    decode = subprocess.Popen(
        [
            cfg["ffmpeg"],
            "-v",
            "error",
            "-ss",
            str(cfg.get("source_in", 0)),
            "-i",
            cfg["source"],
            "-vf",
            f"scale={W}:{H},fps={fps}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    video = out / "silent.mp4"
    enc = subprocess.Popen(
        [
            cfg["ffmpeg"],
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{W}x{H}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert decode.stdout is not None
    assert enc.stdin is not None and enc.stderr is not None
    stats = []
    previous = None
    for n in range(frames):
        t = n / fps
        if n == 0 or n > 1:
            data = decode.stdout.read(W * H * 3)
            if len(data) != W * H * 3:
                raise RuntimeError("Raw presenter ended before planned duration")
            previous = Image.frombytes("RGB", (W, H), data)
        phase_t = min(t, 11.24)
        assert previous is not None
        visual = suite.render_visual(previous, phase_t, media_time=t)
        roles = suite.render_subtitle(phase_t, caption_time=t)
        canvas = visual["background"].copy()
        canvas.alpha_composite(visual["presenter"])
        canvas.alpha_composite(visual["media"])
        text = Image.new("RGBA", (W, H))
        measure = {}
        for key, layer in roles.items():
            canvas.alpha_composite(layer)
            if key not in {"wash", "border"}:
                text.alpha_composite(layer)
            measure[key] = box(layer.getchannel("A"))
            folder = out / "roles" / key
            folder.mkdir(parents=True, exist_ok=True)
            layer.save(folder / f"{n:05}.png", compress_level=2)
        folder = out / "rgba"
        folder.mkdir(exist_ok=True)
        text.save(folder / f"{n:05}.png", compress_level=2)
        occupied = np.asarray(text.getchannel("A")) > 0
        overlap = int(
            (occupied & (np.asarray(roles["border"].getchannel("A")) > 0)).sum()
        )
        stats.append(
            {
                "frame": n,
                "canvas": [W, H],
                "presenterAlphaBox": box(visual["presenter"].getchannel("A")),
                "textVisible": bool(occupied.any()),
                "occludedGlyphPixels": overlap,
                "roles": measure,
            }
        )
        enc.stdin.write(canvas.convert("RGB").tobytes())
        if n % 50 == 0:
            print(out.name, n, frames, flush=True)
    enc.stdin.close()
    error = enc.stderr.read().decode()
    code = enc.wait()
    decode.terminate()
    decode.wait()
    if code:
        raise RuntimeError(error)
    final = out / "final.mp4"
    subprocess.run(
        [
            cfg["ffmpeg"],
            "-v",
            "error",
            "-i",
            str(video),
            "-ss",
            str(cfg.get("source_in", 0)),
            "-i",
            cfg["source"],
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            str(frames / fps),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            str(final),
        ],
        check=True,
    )
    (out / "frame-measurements.json").write_text(
        json.dumps(stats, ensure_ascii=False), encoding="utf8"
    )
    (out / "render-receipt.json").write_text(
        json.dumps(
            {
                "version": "apple-suite-pilot/1",
                "source_sha256": digest(cfg["source"]),
                "material_sha256": digest(cfg.get("media_source") or cfg["ui_image"]),
                "font_sha256": {
                    role: digest(path) for role, path in cfg["fonts"].items()
                },
                "config": cfg,
                "frames": frames,
                "rgba_frames": frames,
                "final_sha256": digest(final),
                "source_code_sha256": SOURCE_SHA256,
                "audio": "original source voice; no inferred FX/BGM",
                "status": "trial, awaiting visual review",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf8",
    )
    if suite.media_capture is not None:
        suite.media_capture.release()
    return final


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--input", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    render(json.loads(args.input.read_text(encoding="utf8")), args.output)
