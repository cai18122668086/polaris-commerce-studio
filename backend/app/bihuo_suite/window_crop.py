"""Presenter window crop that keeps the face (``bihuo-window-crop/1``).

bihuo-02 (bundle fk-1104, kind ``capsule``) fills its presenter window, both
the large opening window and the later circle, from one fixed square of the
source, ``raw_crop`` = rows 420-1500 (``core/capsule_engine.py`` line 53).
A close-up speaker whose face starts above row 420 loses the forehead and
eyes in every frame (e2e 2026-11-26, c-b02).

``raw_crop`` is configuration, not template code, so the host may move it:
before rendering, the face is measured on the actual source (YuNet, 5 samples
per second, median box). Only when the fixed square cuts into the face
(less than ``MIN_HEADROOM`` of the face height above the face box, or the
chin outside the square) the square moves vertically so ``HEADROOM`` of the
face height stays above the face. Size and x are unchanged and one position
holds for the whole clip, so nothing jitters. Runs only with the phase-2
frame policy (``POLARIS_VIDEO_EDITING_FRAME_POLICY=off`` restores the
template crop) and never fails a render.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from . import frame_policy

VERSION = "bihuo-window-crop/1"
H = 1920
MIN_HEADROOM = 0.10
HEADROOM = 0.30
MIN_CHIN_ROOM = 0.05


def _is_capsule(module: Any) -> bool:
    meta = getattr(module, "META", None)
    return isinstance(meta, dict) and meta.get("kind") == "capsule"


def adjusted_crop(
    crop: list[float], face: list[int], low: float = 0.0, high: float = H
) -> tuple[list[float], str]:
    """The crop to use for a median face box, and why.

    ``low``/``high`` bound the rows with real picture: a reframed source
    (``bihuo-reframe/1``) has a blurred fill band that must stay out of view.
    """
    x, y, w, h = (float(v) for v in crop)
    top, bottom = float(face[1]), float(face[3])
    size = bottom - top
    if size <= 0:
        return list(crop), "no face size"
    cuts_top = y > top - MIN_HEADROOM * size
    cuts_chin = y + h < bottom + MIN_CHIN_ROOM * size
    if not (cuts_top or cuts_chin):
        return list(crop), "face already inside the crop"
    if size * (1 + HEADROOM + MIN_CHIN_ROOM) <= h:
        new_y = top - HEADROOM * size
    else:  # face larger than the window: centre it
        new_y = (top + bottom) / 2 - h / 2
    new_y = max(low, min(high - h, new_y))
    if round(new_y) == round(y):
        return list(crop), "no room inside the real picture"
    return [x, round(new_y), w, h], "moved to keep the face"


@contextmanager
def execution(module: Any, payload: dict[str, Any]) -> Iterator[dict | None]:
    config = payload.get("config") if isinstance(payload, dict) else None
    if (
        not _is_capsule(module)
        or not frame_policy.enabled(payload)
        or not isinstance(config, dict)
        or not isinstance(config.get("raw_crop"), list)
        or config.get("source_mode") == "reference-window"
    ):
        yield None
        return
    original = list(config["raw_crop"])
    record: dict[str, Any] = {"version": VERSION, "original": original}
    try:
        from .reframe import measure

        measured = measure(config["source"], config.get("ffmpeg") or "ffmpeg")
        record["measured"] = measured
        box = measured.get("median_box")
        shift = 0
        reframed = config.get("source_reframe") or {}
        if reframed.get("applied"):
            shift = int(reframed.get("shift_px") or 0)
        low, high = float(max(0, shift)), float(H - max(0, -shift))
        record["picture_rows"] = [low, high]
        if box and measured["found"] >= 0.5 * max(1, measured["samples"]):
            crop, reason = adjusted_crop(original, box, low, high)
        else:
            crop, reason = original, "face not reliably found"
    except Exception as error:  # measurement never fails a render
        crop, reason = original, f"{type(error).__name__}: {error}"[:200]
    record.update(crop=crop, applied=crop != original, reason=reason)
    config["raw_crop"] = crop
    try:
        yield record
    finally:
        config["raw_crop"] = original
