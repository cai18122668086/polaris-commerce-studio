"""Timed video frames for native image slots, without changing frozen recipes.

The planner keeps real video IDs, hashes, durations and spoken spans. Only the
native image-slot execution uses a measured 25fps frame stream. Images and old
compiled jobs are untouched; source speech is the sole audio track.
"""

from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from ..motion_library import atomic_json, read_json, sha256
from ..video_editing_pipeline import run

VERSION = "bihuo-video-materials/1"
NATIVE_VIDEO = {"bihuo-02-v1", "bihuo-03-v1", "bihuo-04-v1"}


def capabilities(meta: dict) -> list[str]:
    values = list(meta.get("capabilities", []))
    if "video_materials" not in values:
        values.append("video_materials")
    return values


def identity() -> dict:
    return {"version": VERSION, "sha256": sha256(Path(__file__))}


def _frames(
    material: dict,
    duration: float,
    root: Path,
    settings: Any,
    guard: Callable,
) -> dict:
    source = Path(material["path"]).resolve(strict=True)
    digest = sha256(source)
    if material.get("sha256") != digest:
        raise ValueError("Video material changed before frame preparation")
    measured = material.get("duration")
    if (
        not isinstance(measured, (int, float))
        or not math.isfinite(measured)
        or measured <= 0
    ):
        raise ValueError("Video material needs its measured duration")
    count = max(1, math.ceil(min(measured, duration) * 25))
    folder = root / "video-materials" / (digest + f"-{count}")
    receipt = folder / "frames.json"
    if receipt.exists():
        cached = read_json(receipt)
        if cached["source_sha256"] != digest or cached["requested_frames"] != count:
            raise ValueError("Video frame cache belongs to another material")
        return cached
    folder.mkdir(parents=True, exist_ok=False)
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "fps=25,scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
            "-frames:v",
            str(count),
            "-q:v",
            "2",
            str(folder / "f%06d.jpg"),
        ],
        root,
        settings,
        guard,
        "prepare_video_material_" + digest[:12],
    )
    paths = sorted(folder.glob("f*.jpg"))
    if not paths or len(paths) > count or sha256(source) != digest:
        raise ValueError("Video material ended without a usable frame stream")
    # JPEG extraction is bounded by the assigned display interval. Short clips
    # hold their last measured frame, without retiming the source speech.
    result = {
        "source_path": str(source),
        "source_sha256": digest,
        "source_duration": measured,
        "fps": 25,
        "requested_frames": count,
        "frames": [{"path": str(p), "sha256": sha256(p)} for p in paths],
    }
    atomic_json(receipt, result)
    return result


def compile_request(
    template_id: str,
    resolved: dict,
    compiler: Callable[..., dict],
    *,
    root: Path,
    settings: Any,
    guard: Callable,
    **kwargs: Any,
) -> dict:
    videos = [m for m in resolved.get("materials", []) if m.get("kind") == "video"]
    if not videos or template_id in NATIVE_VIDEO:
        from .adaptive_layout import compilation

        with compilation(template_id):
            return compiler(template_id, resolved, **kwargs)
    native = copy.deepcopy(resolved)
    streams = []
    prepared = {}
    for i, original in enumerate(resolved["materials"]):
        if original.get("kind") != "video":
            continue
        # The entire speech duration bounds any native entry/exit extension.
        key = original["sha256"]
        if key not in prepared:
            prepared[key] = _frames(
                original, resolved["duration"], root, settings, guard
            )
        stream = prepared[key]
        proxy = root / "video-materials" / f"slot-{i:03d}.jpg"
        raw = Path(stream["frames"][0]["path"]).read_bytes()
        if proxy.exists():
            if proxy.read_bytes() != raw:
                raise ValueError("Video slot proxy changed")
        else:
            proxy.write_bytes(raw)
        native["materials"][i].update(
            kind="image", path=str(proxy), sha256=hashlib.sha256(raw).hexdigest()
        )
        streams.append(
            {
                **stream,
                "asset_id": original["asset_id"],
                "proxy_path": str(proxy),
                "start": original["start"],
                "end_policy": "hold",
                "audio": "muted",
            }
        )
    payload = compiler(template_id, native, **kwargs)
    cfg = payload["config"]

    # Bind playback to the concrete native slot's first frame. Some recipes
    # use spoken-span start, some use the selected show-at word.
    def slot_start(value: Any, proxy: str) -> float | None:
        if isinstance(value, dict):
            if value.get("path") == proxy and "start" in value:
                start = value["start"]
                return start / 25 if isinstance(start, int) else float(start)
            for k, child in value.items():
                if (
                    k != "resolved_plan"
                    and (found := slot_start(child, proxy)) is not None
                ):
                    return found
        elif isinstance(value, list):
            for child in value:
                if (found := slot_start(child, proxy)) is not None:
                    return found
        return None

    for stream in streams:
        start = slot_start(cfg, stream["proxy_path"])
        if start is not None:
            stream["start"] = start
    cfg["resolved_plan"] = copy.deepcopy(resolved)
    if "actual_image_asset_ids" in cfg:
        video_ids = {v["asset_id"] for v in streams}
        cfg["actual_image_asset_ids"] = [
            x for x in cfg["actual_image_asset_ids"] if x not in video_ids
        ]
        cfg["actual_video_asset_ids"] = sorted(video_ids)
    cfg["video_materials"] = {**identity(), "streams": streams}
    return payload


class VideoFrames:
    def __init__(self, config: dict) -> None:
        policy = config["video_materials"]
        if any(policy.get(k) != v for k, v in identity().items()):
            raise ValueError("Video material policy differs from compiled input")
        self.streams = {v["proxy_path"]: v for v in policy["streams"]}
        self.verified: set[str] = set()
        for stream in self.streams.values():
            if (
                not stream["frames"]
                or sha256(Path(stream["source_path"])) != stream["source_sha256"]
            ):
                raise ValueError("Original video material changed")

    def bind(self, cfg: dict, frame: int) -> dict:
        paths = {}
        for proxy, stream in self.streams.items():
            index = max(
                0,
                min(
                    len(stream["frames"]) - 1,
                    math.floor(frame - stream["start"] * 25 + 1e-6),
                ),
            )
            row = stream["frames"][index]
            path = row["path"]
            if path not in self.verified:
                if sha256(Path(path)) != row["sha256"]:
                    raise ValueError("Prepared video material frame changed")
                self.verified.add(path)
            paths[proxy] = path

        def replace(value: Any) -> Any:
            if isinstance(value, str):
                return paths.get(value, value)
            if isinstance(value, list):
                return [replace(x) for x in value]
            if isinstance(value, dict):
                return {
                    k: v if k in {"resolved_plan", "video_materials"} else replace(v)
                    for k, v in value.items()
                }
            return value

        return replace(cfg)


@contextmanager
def execution(module: Any, payload: dict) -> Iterator[None]:
    cfg = payload["config"]
    if not cfg.get("video_materials"):
        yield
        return
    frames = VideoFrames(cfg)
    if hasattr(module, "render_frame"):
        namespace, name, offset = vars(module), "render_frame", 0
    elif hasattr(module, "render_layers"):
        namespace, name, offset = vars(module), "render_layers", 0
    else:
        namespace, name, offset = module.encode.__globals__, "render", 1
    original = namespace[name]

    @wraps(original)
    def timed(*args: Any, **kwargs: Any) -> Any:
        values = list(args)
        values[offset] = frames.bind(values[offset], values[offset + 1])
        return original(*values, **kwargs)

    namespace[name] = timed
    try:
        yield
    finally:
        namespace[name] = original
