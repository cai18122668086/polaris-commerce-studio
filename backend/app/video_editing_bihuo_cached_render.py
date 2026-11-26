"""Transparent acceleration around the unchanged, frozen suite renderer.

The template/planner identity stays unchanged so saved responses and plans can
continue. The receipt separately binds the accelerator's actual source bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from .bihuo_suite import (
    conditional_layout,
    frame_policy,
    layer_timeline,
    opening_card,
    raster_cache,
    video_materials,
    window_crop,
)
from .bihuo_suite.registry import runtime
from .bihuo_suite.render import render as native_render


def render(payload: dict, output: Path) -> Path:
    # Match the native entry point before importing any native bundle.
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(key, "1")
    import cv2

    cv2.setNumThreads(1)
    module = runtime(payload["template_id"])
    started = time.monotonic()
    with (
        raster_cache.native_raster_cache(module) as rasters,
        conditional_layout.execution(module, payload),
        video_materials.execution(module, payload),
        opening_card.execution(module, payload) as opening,
        window_crop.execution(module, payload) as cropping,
        # Inside the timeline so it records the layers actually shown.
        frame_policy.execution(module, payload) as framing,
        layer_timeline.recording(module) as timeline,
    ):
        final = native_render(payload, output)
    timeline_receipt = timeline.write(output)
    framing_receipt = (
        framing.write(output)
        if framing is not None
        else frame_policy.unsupported(payload, module)
    )
    receipt = output / "render-receipt.json"
    value = json.loads(receipt.read_text("utf-8"))
    value.update(
        conditional_layout=payload["config"].get("conditional_layout"),
        video_materials=payload["config"].get("video_materials"),
        sync_policy=(payload["config"].get("sync_policy") or {}).get("version"),
        layer_timeline=timeline_receipt,
        frame_policy=framing_receipt,
        source_reframe=payload["config"].get("source_reframe"),
        opening_card=opening.receipt() if opening is not None else None,
        window_crop=cropping,
        render_seconds=round(time.monotonic() - started, 3),
        raster_cache_hits=rasters.hits,
        raster_cache_misses=rasters.misses,
        execution_accelerator={
            "version": "native-glyph-cache/1",
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cache_sha256": hashlib.sha256(
                Path(raster_cache.__file__).read_bytes()
            ).hexdigest(),
        },
    )
    receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(json.loads(args.input.read_text("utf-8")), args.output)


if __name__ == "__main__":
    main()
