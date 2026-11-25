"""Static presenter reframe before a full-suite render (``bihuo-reframe/1``).

Suite templates crop the presenter with fixed boxes measured on the reference
sample (for example bihuo-02 shows source rows 420-1500 in its window, bihuo-24
a 780 px tall window). A source whose face sits much higher or lower than the
reference loses the head in every windowed template, which no overlay move can
repair. This step measures the face on the prepared 1080x1920 source (YuNet,
5 samples per second) and, only when the median face centre is outside
``BAND``, shifts the whole picture vertically so the centre lands on
``TARGET_CY``; the exposed edge is filled with a blurred stretch of the
picture's own edge rows. One shift for the whole clip: nothing can jitter.

The speech clock and audio are untouched (stream copy). Runs after
``bihuo_suite/source.py`` (part of the template identity, so not edited) and
the tail hold, and before the foreground matte so the matte sees the same
picture. Every decision is written to ``suite-source-reframe.json``.
"""

from __future__ import annotations

import statistics
import subprocess
from pathlib import Path
from typing import Any

from ..motion_library import atomic_json, sha256
from . import subject

VERSION = "bihuo-reframe/1"
W, H = 1080, 1920
# Reference presenters (bihuo samples, lipsync a84/ee233) put the face centre
# at y ~ 520-560 with the face about 400 px tall.
TARGET_CY = 540
BAND = (400, 760)
MAX_SHIFT = 420
MIN_FOUND_SHARE = 0.5
SAMPLE_FPS = 5
EDGE_ROWS = 24
CORNER = 120


def measure(source: Path, ffmpeg: str, timeout: float = 600) -> dict[str, Any]:
    import numpy as np
    from PIL import Image

    scale = subject.SCALE
    w, h = W // scale, H // scale
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-an",
            "-vf",
            f"fps={SAMPLE_FPS},scale={w}:{h}:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    detector = subject.FaceDetector((W, H))
    boxes = []
    for small in frames:
        found = detector.detect(Image.fromarray(small).resize((W, H)))
        if found:
            boxes.append(found[0])
    result: dict[str, Any] = {"samples": int(len(frames)), "found": len(boxes)}
    if boxes:
        result["median_box"] = [
            round(statistics.median(b[i] for b in boxes)) for i in range(4)
        ]
    return result


def shift_for(measured: dict[str, Any]) -> int:
    box = measured.get("median_box")
    samples = measured.get("samples") or 0
    if not box or not samples or measured["found"] < MIN_FOUND_SHARE * samples:
        return 0
    centre = (box[1] + box[3]) / 2
    if BAND[0] <= centre <= BAND[1]:
        return 0
    shift = round(TARGET_CY - centre)
    # Never push the face itself out of the frame.
    shift = max(-box[1], min(H - box[3], shift))
    return max(-MAX_SHIFT, min(MAX_SHIFT, shift)) // 2 * 2


def filter_graph(shift: int) -> str:
    """Shift the picture; fill the exposed edge from the two corners.

    The middle of the edge rows is usually the presenter (hair at the top,
    body at the bottom); the corners are the background, so the fill is a
    heavily blurred stretch of the left and right corner patches.
    """
    d = abs(shift)
    half = W // 2
    y = 0 if shift > 0 else H - EDGE_ROWS
    corners = (
        f"[b]crop={CORNER}:{EDGE_ROWS}:0:{y},scale={half}:{d}:flags=bilinear[l];"
        f"[c]crop={CORNER}:{EDGE_ROWS}:{W - CORNER}:{y},"
        f"scale={half}:{d}:flags=bilinear[r];"
        f"[l][r]hstack=inputs=2,gblur=sigma=40[e];"
    )
    if shift > 0:
        return (
            f"[0:v]split=3[a][b][c];{corners}"
            f"[a]crop={W}:{H - d}:0:0[m];[e][m]vstack=inputs=2,setsar=1[v]"
        )
    return (
        f"[0:v]split=3[a][b][c];{corners}"
        f"[a]crop={W}:{H - d}:0:{d}[m];[m][e]vstack=inputs=2,setsar=1[v]"
    )


def prepare(
    source: Path, root: Path, settings: Any, guard: Any, run: Any = None
) -> tuple[Path, dict[str, Any]]:
    """Return the source to render and the reframe receipt."""
    receipt: dict[str, Any] = {"version": VERSION, "source_sha256": sha256(source)}
    if not subject.model_available():
        receipt.update(applied=False, reason="face model unavailable")
        atomic_json(root / "suite-source-reframe.json", receipt)
        return source, receipt
    try:
        measured = measure(source, settings.video_editing_ffmpeg)
    except Exception as error:  # measurement never fails a render
        receipt.update(applied=False, reason=f"{type(error).__name__}: {error}"[:300])
        atomic_json(root / "suite-source-reframe.json", receipt)
        return source, receipt
    shift = shift_for(measured)
    receipt.update(measured=measured, target_cy=TARGET_CY, band=list(BAND))
    if not shift:
        receipt.update(applied=False, shift_px=0)
        atomic_json(root / "suite-source-reframe.json", receipt)
        return source, receipt
    if run is None:
        from ..video_editing_pipeline import run
    target = root / "suite-source-reframed.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-filter_complex",
            filter_graph(shift),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ],
        root,
        settings,
        guard,
        "reframe_suite_source",
    )
    receipt.update(
        applied=True,
        shift_px=shift,
        fill="blurred edge rows",
        prepared_sha256=sha256(target),
        speech_clock="unchanged; audio stream copied",
    )
    atomic_json(root / "suite-source-reframe.json", receipt)
    return target, receipt
