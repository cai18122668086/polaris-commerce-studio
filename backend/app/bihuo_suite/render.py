"""Execute an installed template in the existing isolated renderer process."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from .raster_cache import native_raster_cache
from .registry import runtime


def render(payload: dict, output: Path) -> Path:
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(key, "1")
    import cv2

    cv2.setNumThreads(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Suite output directory must be new")
    module = runtime(payload["template_id"])
    started = time.monotonic()
    with native_raster_cache(module) as rasters:
        final = Path(module.render_mp4(payload["config"], output))
    if not final.is_file() or not final.resolve().is_relative_to(output.resolve()):
        raise ValueError("Suite did not produce a video in its output directory")
    receipt = output / "render-receipt.json"
    value = json.loads(receipt.read_text("utf-8")) if receipt.is_file() else {}
    value.update(
        template_id=payload["template_id"],
        final_sha256=hashlib.sha256(final.read_bytes()).hexdigest(),
        render_seconds=round(time.monotonic() - started, 3),
        raster_cache_hits=rasters.hits,
        raster_cache_misses=rasters.misses,
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
