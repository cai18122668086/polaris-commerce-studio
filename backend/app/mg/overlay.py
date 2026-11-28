"""Composite planned MG cues onto a finished suite render (post-process).

Runs inside the isolated suite render process right after the unchanged
template renderer wrote ``final.mp4`` (``video_editing_bihuo_cached_render``).
The preview is built later from this same file, so preview and export carry
identical MG; each render writes a new output directory, so it is applied
exactly once per render.

Placement per cue:
* skipped where the template shows supplement material (``material`` role);
* cards avoid the presenter face (YuNet on the final frames), the caption
  box and the template's own overlay cards (``layers-timeline.jsonl``);
* full-screen components are limited to 2.5 s;
* no free space → the cue is dropped (warning), never forced over a face.

Encoding matches the templates' export: libx264, yuv420p, CRF 18, the
source's own frame rate, audio stream copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from .brand import LIMIT, check_image
from .catalog import CATALOG_VERSION, COMPONENTS, STYLES, box_size, cue_window

VERSION = "mg-overlay/1"
SAFE_TOP, SAFE_BOTTOM, MARGIN = 200, 240, 24
SCALES = (1.0, 0.9, 0.8, 0.72, 0.68)
EDGE = 48
IGNORED_ROLES = ("background", "presenter", "stage", "raw")
CAPTION_ROLES = ("caption", "subtitle")
Box = tuple[int, int, int, int]


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe(ffprobe: str, path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    rate = Fraction(stream["r_frame_rate"])
    duration = float(data["format"]["duration"])
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "rate": rate,
        "fps": float(rate),
        "duration_ms": round(duration * 1000),
        "frames": int(stream.get("nb_frames") or round(duration * float(rate))),
    }


def load_timeline(output: Path) -> list[dict[str, Any]]:
    path = output / "layers-timeline.jsonl"
    rows = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                rows.append(json.loads(line))
    except (OSError, ValueError):
        return []
    return rows


def overlaps(a: Box, b: Box, margin: int = 0) -> bool:
    return (
        a[0] < b[2] + margin
        and b[0] < a[2] + margin
        and a[1] < b[3] + margin
        and b[1] < a[3] + margin
    )


def occupancy(
    timeline: list[dict[str, Any]], first: int, last: int, scale: float
) -> dict[str, Any]:
    """Boxes the cue must avoid between frames first..last (video frames)."""
    boxes: list[Box] = []
    presenter: list[Box] = []
    material_frames = sampled = 0
    if not timeline:
        return {"boxes": [], "presenter": [], "material": False, "known": False}
    for n in range(first, last + 1, 3):
        index = min(len(timeline) - 1, round(n * scale))
        roles = timeline[index].get("roles") or {}
        sampled += 1
        for name, entry in roles.items():
            bbox = entry.get("bbox")
            if not bbox or entry.get("peak", 0) < 0.15:
                continue
            box = tuple(int(v) for v in bbox)
            if name == "material":
                material_frames += 1
                continue
            if name == "presenter":
                presenter.append(box)  # type: ignore[arg-type]
                continue
            if any(name.startswith(prefix) for prefix in IGNORED_ROLES):
                continue
            boxes.append(box)  # type: ignore[arg-type]
    return {
        "boxes": boxes,
        "presenter": presenter,
        "material": sampled > 0 and material_frames / sampled > 0.3,
        "known": True,
    }


def faces(
    ffmpeg: str, final: Path, times: list[float], size: tuple[int, int]
) -> list[Box]:
    """Expanded face boxes on the final frames at ``times`` (seconds)."""
    try:
        from PIL import Image

        from ..bihuo_suite.subject import FaceDetector, expand, model_available

        if not model_available():
            return []
        detector = FaceDetector(size)
    except Exception:  # noqa: BLE001 — no detector → presenter fallback
        return []
    found = []
    for t in times:
        raw = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                f"{max(0.0, t):.3f}",
                "-i",
                str(final),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            timeout=60,
        ).stdout
        if len(raw) != size[0] * size[1] * 3:
            continue
        hit = detector.detect(Image.frombytes("RGB", size, raw))
        if hit:
            found.append(expand(hit[0], 0.4, 0.55, 0.4, 0.45))
    return found


def place(
    component: str,
    blocked: list[Box],
    size: tuple[int, int],
    params: dict[str, Any] | None = None,
) -> tuple[int, int, float] | None:
    """Free spot (x, y, scale), preferring full size and the upper centre.

    Cards may shrink to the last of ``SCALES`` (smallest card text stays
    ≥30 px at 1080 wide); never over the face, captions or template cards.
    """
    if COMPONENTS[component].get("fullscreen"):
        return (0, 0, 1.0)
    base_w, base_h = box_size(component, params or {})
    for scale in SCALES:
        width, height = round(base_w * scale), round(base_h * scale)
        xs = dict.fromkeys(((size[0] - width) // 2, EDGE, size[0] - EDGE - width))
        for y in range(SAFE_TOP, size[1] - SAFE_BOTTOM - height + 1, 20):
            for x in xs:
                if x < EDGE // 2 or x + width > size[0] - EDGE // 2:
                    continue
                rect = (x, y, x + width, y + height)
                if not any(overlaps(rect, box, MARGIN) for box in blocked):
                    return (x, y, scale)
    return None


def schedule(
    cues: list[dict[str, Any]],
    info: dict[str, Any],
    timeline: list[dict[str, Any]],
    final: Path,
    ffmpeg: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    fps, size = info["fps"], (info["width"], info["height"])
    scale = len(timeline) / info["frames"] if timeline and info["frames"] else 1.0
    planned, warnings = [], []
    previous_end = -1
    for cue in sorted(cues, key=lambda row: row["start_ms"]):
        component = cue["component"]
        window = cue_window(
            component, cue["start_ms"], cue["end_ms"], info["duration_ms"]
        )
        if window is None:
            warnings.append(f"{component}:too_short")
            continue
        first = round(window[0] / 1000 * fps)
        last = min(info["frames"] - 1, round(window[1] / 1000 * fps) - 1)
        if first <= previous_end or last - first < 20:
            warnings.append(f"{component}:overlap")
            continue
        busy = occupancy(timeline, first, last, scale)
        if busy["material"]:
            warnings.append(f"{component}:material_present")
            continue
        blocked: list[Box] = list(busy["boxes"])
        if not COMPONENTS[component].get("fullscreen"):
            found = faces(
                ffmpeg, final, [first / fps, (first + last) / 2 / fps, last / fps], size
            )
            if found:
                blocked.extend(found)
            else:
                # No face measured: keep clear of the presenter's upper half.
                for box in busy["presenter"]:
                    blocked.append((box[0], box[1], box[2], (box[1] + box[3]) // 2))
        spot = place(component, blocked, size, cue.get("params"))
        if spot is None:
            warnings.append(f"{component}:no_space")
            continue
        planned.append(
            {
                **cue,
                "first_frame": first,
                "last_frame": last,
                "x": spot[0],
                "y": spot[1],
                "scale": spot[2],
                "avoided": len(blocked),
            }
        )
        previous_end = last
    return planned, warnings


def composite(
    ffmpeg: str,
    final: Path,
    planned: list[dict[str, Any]],
    rate: Fraction,
    target: Path,
) -> None:
    command = [ffmpeg, "-v", "error", "-y", "-i", str(final)]
    graph, label = [], "0:v"
    for index, cue in enumerate(planned, start=1):
        command += [
            "-framerate",
            f"{rate.numerator}/{rate.denominator}",
            "-i",
            str(Path(cue["frames_dir"]) / "%05d.png"),
        ]
        offset = f"{cue['first_frame']}*{rate.denominator}/{rate.numerator}"
        scale = cue.get("scale", 1.0)
        resize = f",scale=iw*{scale}:ih*{scale}:flags=lanczos" if scale < 1 else ""
        graph.append(
            f"[{index}:v]format=rgba{resize},"
            f"setpts=PTS-STARTPTS+({offset})/TB[m{index}]"
        )
        graph.append(
            f"[{label}][m{index}]overlay=x={cue['x']}:y={cue['y']}:eof_action=pass:"
            f"enable='between(n,{cue['first_frame']},{cue['last_frame']})'[v{index}]"
        )
        label = f"v{index}"
    command += [
        "-filter_complex",
        ";".join(graph),
        "-map",
        f"[{label}]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{rate.numerator}/{rate.denominator}",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=1800)


def apply_supplement_mg(
    payload: dict[str, Any],
    output: Path,
    final: Path,
    *,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> dict[str, Any] | None:
    """Overlay ``payload['supplement_mg']`` onto ``final`` in place.

    Returns the receipt (None when the task did not ask for MG). Any failure
    keeps the original render and records the reason: MG never fails a cut.
    """
    request = payload.get("supplement_mg")
    if not request:
        return None
    from .catalog import template_supported

    if not template_supported(payload.get("template_id")):
        return {
            "version": VERSION,
            "catalog": CATALOG_VERSION,
            "status": "template_not_supported",
            "template_id": payload.get("template_id"),
        }
    started = time.monotonic()
    ffmpeg = ffmpeg or request.get("ffmpeg") or "ffmpeg"
    ffprobe = ffprobe or request.get("ffprobe") or "ffprobe"
    style = request.get("style") if request.get("style") in STYLES else "paper"
    receipt: dict[str, Any] = {
        "version": VERSION,
        "catalog": CATALOG_VERSION,
        "style": style,
        "plan_digest": request.get("plan_digest"),
        "plan_source": request.get("source"),
        "requested": len(request.get("cues") or []),
        "applied": [],
        "warnings": list(request.get("warnings") or []),
    }
    work = output / "mg-work"
    try:
        from .render import browser, render_cue, verify_resources

        receipt["resources"] = verify_resources()
        info = probe(ffprobe, final)
        receipt["video"] = {
            "fps": f"{info['rate'].numerator}/{info['rate'].denominator}",
            "width": info["width"],
            "height": info["height"],
            "base_sha256": _sha(final),
        }
        planned, warnings = schedule(
            request.get("cues") or [], info, load_timeline(output), final, ffmpeg
        )
        receipt["warnings"] += warnings
        if not planned:
            receipt["status"] = "nothing_to_apply"
            return receipt
        with browser() as instance:
            for index, cue in enumerate(planned):
                folder = work / f"cue{index:02d}"
                paths = render_cue(
                    instance,
                    folder,
                    cue["component"],
                    cue["params"],
                    style,
                    cue["last_frame"] - cue["first_frame"] + 1,
                    info["fps"],
                )
                sample = [
                    paths[len(paths) // 3],
                    paths[len(paths) // 2],
                    paths[-12 if len(paths) > 12 else -1],
                ]
                worst = max(check_image(path) for path in sample)
                if worst > LIMIT:
                    raise ValueError(
                        f"MG brand check failed: {cue['component']} {worst:.4f}"
                    )
                cue["frames_dir"] = str(folder)
                cue["brand_ratio"] = round(worst, 5)
        target = output / ".mg-final.mp4"
        composite(ffmpeg, final, planned, info["rate"], target)
        after = probe(ffprobe, target)
        if (
            after["frames"] != info["frames"]
            or abs(after["duration_ms"] - info["duration_ms"]) > 80
        ):
            target.unlink(missing_ok=True)
            raise ValueError("MG composite changed the clock")
        receipt["size_before"] = final.stat().st_size
        os.replace(target, final)
        receipt["size_after"] = final.stat().st_size
        receipt["final_sha256"] = _sha(final)
        receipt["applied"] = [
            {
                key: cue[key]
                for key in (
                    "component",
                    "params",
                    "start_ms",
                    "end_ms",
                    "first_frame",
                    "last_frame",
                    "x",
                    "y",
                    "scale",
                    "brand_ratio",
                )
            }
            for cue in planned
        ]
        receipt["status"] = "applied"
    except Exception as error:  # noqa: BLE001 — keep the clean render
        receipt["status"] = "failed"
        receipt["error"] = f"{type(error).__name__}: {error}"[:300]
    finally:
        shutil.rmtree(work, ignore_errors=True)
        receipt["seconds"] = round(time.monotonic() - started, 2)
    return receipt
