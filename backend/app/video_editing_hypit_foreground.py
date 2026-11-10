"""Render current Hypit foreground media with the original presenter matte."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps

from .motion_library import atomic_json, read_json, sha256
from .video_editing_media_clocks import clock_profile

FOREGROUND_MATTE = "model-01eb6a29a5c4d8edb30b"
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_MATTE = (
    _OWNER / "新增批次/晨曦_Broll画面排版_7704151605411546024/trial-CXBR02/matting.py"
)
_SAMPLER = _OWNER / "unified/core/media.py"
_NATIVE = Path("commercial_runtime/native.py")
# HY-A2's original fg="mkfg1@483,1014,597,906" is above stagger layer 10.
_FOREGROUND_SIZE = 598, 906
_SOURCE_SIZE = 720, 1280
_STYLE = """
  media.foreground { stack-order: 11; fit: cover; }
"""


def _foreground_profile(package: Path) -> dict[str, Any]:
    profile = clock_profile("CXBR02")
    if not profile or any(
        sha256(package / path) != profile["source_files"][path.as_posix()]
        for path in (_MATTE, _SAMPLER, _NATIVE)
    ):
        raise ValueError("Original presenter sampler or matte changed")
    return profile


def load_foreground_source(package: Path, model: Path, cache: Path) -> tuple[Any, Any]:
    _foreground_profile(package)
    sys.path[:0] = [str(package), str(package / _OWNER)]
    try:
        native = importlib.import_module("commercial_runtime.native")
        media = importlib.import_module("unified.core.media")
    finally:
        del sys.path[:2]
    for module, expected in ((native, _NATIVE), (media, _SAMPLER)):
        if not module.__file__ or Path(module.__file__).resolve() != package / expected:
            raise ValueError("Foreground requires its original native modules")
    matte_module = native.module(package / _MATTE, "tengli_original_foreground_matte")
    return media, matte_module.HumanMatte(model, cache)


def attach_foreground_track(
    scene: str, style_file: Path, *, full_source: bool = False
) -> str:
    asset = '  <import as="asset" from="@hypit/media@1"/>\n'
    canvas = '  <spatial:Canvas id="canvas" width="1080" height="1920"/>\n'
    cards = "    <film:Track source={a2m.track}/>\n"
    if any(scene.count(mark) != 1 for mark in (asset, canvas, cards)):
        raise ValueError("Original slant card foreground anchors changed")
    imports = (
        '  <import as="pipeline" from="@hypit/media-pipeline@1"/>\n'
        '  <import as="media-track" from="@hypit/media-track@1"/>\n'
    )
    left, top = (0, 0) if full_source else (483, 1014)
    track = (
        '  <spatial:Frame id="tengli-fg-frame" within={canvas}\n'
        f'    left="{left}px" top="{top}px" right="1080px" bottom="1920px"/>\n'
        """  <asset:Video id="tengli-fg-source" src="./inputs/current-foreground.webm"/>
  <pipeline:Normalize id="tengli-fg-media" source={tengli-fg-source}
    video="primary-moving" audio="none" span-authority="video" clock={clock}/>
  <media-track:Track id="tengli-fg-track" timeline={t.timeline} canvas={canvas}>
    <media-track:Item id="tengli-fg-item" frame={tengli-fg-frame}
      media={tengli-fg-media.media} appearance={style.media.foreground}
      during="program"/>
  </media-track:Track>
"""
    )
    styles = style_file.read_text(encoding="utf-8")
    if styles.count("</sheet>") != 1:
        raise ValueError("Original slant card appearance sheet changed")
    style_file.write_text(
        styles.replace("</sheet>", _STYLE + "</sheet>"), encoding="utf-8"
    )
    return (
        scene.replace(asset, asset + imports)
        .replace(canvas, canvas + track)
        .replace(cards, cards + "    <film:Track source={tengli-fg-track.visual}/>\n")
    )


def render_foreground(
    package: Path,
    original: Any,
    source_ref: str,
    window: dict,
    clip: Path,
    *,
    full_source: bool = False,
) -> dict:
    source = Path(original.resolve(source_ref, True))
    model = Path(original.resolve("input://" + FOREGROUND_MATTE, True))
    if sha256(source) != window["source_sha256"]:
        raise ValueError("Slant card presenter differs from the compiled source window")
    profile = _foreground_profile(package)
    size = _SOURCE_SIZE if full_source else _FOREGROUND_SIZE
    identity = {
        "source_window": window,
        "model_sha256": sha256(model),
        "sampler_sha256": profile["source_files"][_SAMPLER.as_posix()],
        "matte_sha256": profile["source_files"][_MATTE.as_posix()],
        "size": list(size),
        "placement": "source-frame" if full_source else "proportional-inset",
    }
    receipt = clip.with_suffix(".json")
    if receipt.is_file() and clip.is_file():
        existing = read_json(receipt)
        if existing["identity"] == identity and existing["sha256"] == sha256(clip):
            return existing

    media, matte = load_foreground_source(
        package, model, clip.parent.parent / "matte-cache"
    )
    frames = window["frames"]
    asset = media.inspect_asset(
        {
            "path": str(source),
            "offset_seconds": window["source_start_ms"] / 1000,
            "duration_seconds": frames / 30,
            "end_policy": "error",
        }
    )
    clip.parent.mkdir(parents=True, exist_ok=True)
    temporary = clip.with_name(f"foreground-{uuid4().hex[:8]}.pending.webm")
    cmd = [
        original.resolve("tool://ffmpeg", True),
        "-nostdin",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgba",
        "-video_size",
        f"{size[0]}x{size[1]}",
        "-framerate",
        "30",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-auto-alt-ref",
        "0",
        "-threads",
        "4",
        "-cpu-used",
        "4",
        "-b:v",
        "0",
        "-crf",
        "16",
        "-n",
        str(temporary),
    ]
    try:
        with (
            clip.with_suffix(".log").open("wb") as log,
            subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
            ) as encoder,
        ):
            assert encoder.stdin is not None
            try:
                for i in range(frames):
                    picture = media.asset_frame(asset, i / 30, native_size=True)
                    working = ImageOps.contain(picture, size, Image.Resampling.LANCZOS)
                    cutout = matte.apply(
                        working,
                        f"{window['source_sha256']}-{window['source_start_ms']}-"
                        f"{working.width}x{working.height}-{i}",
                    )
                    # Keep the same geometry in both axes. The inset can have
                    # transparent margins instead of stretching the presenter.
                    frame = Image.new("RGBA", size)
                    frame.paste(
                        cutout,
                        ((size[0] - cutout.width) // 2, (size[1] - cutout.height) // 2),
                    )
                    encoder.stdin.write(frame.tobytes())
                encoder.stdin.close()
                if encoder.wait(timeout=120):
                    raise ValueError("Hypit foreground alpha encoding failed")
            except BaseException:
                encoder.kill()
                encoder.wait()
                raise
        observed = subprocess.check_output(
            [
                original.resolve("tool://ffprobe", True),
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames,width,height:stream_tags=alpha_mode",
                "-of",
                "json",
                str(temporary),
            ],
            timeout=120,
        )
        stream = json.loads(observed)["streams"][0]
        tags = {key.lower(): value for key, value in stream.get("tags", {}).items()}
        if (
            int(stream["nb_read_frames"]) != frames
            or (stream["width"], stream["height"]) != size
            or tags.get("alpha_mode") != "1"
        ):
            raise ValueError("Hypit foreground does not cover its alpha frame window")
        os.replace(temporary, clip)
        result = {
            "identity": identity,
            "sha256": sha256(clip),
            "alpha": "straight",
            "frames": frames,
            "native_box": [0, 0, 1080, 1920] if full_source else [483, 1014, 597, 906],
        }
        atomic_json(receipt, result)
        return result
    finally:
        temporary.unlink(missing_ok=True)
