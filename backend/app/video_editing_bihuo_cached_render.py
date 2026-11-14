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

from .bihuo_suite import raster_cache
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
    with raster_cache.native_raster_cache(module) as rasters:
        final = native_render(payload, output)
    receipt = output / "render-receipt.json"
    value = json.loads(receipt.read_text("utf-8"))
    value.update(
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
