"""Worker-owned source-bound native alpha cache shared across full suites."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import Settings
from ..motion_library import atomic_json, read_json, sha256
from ..motion_local_dependencies import read_dependency_manifest, resolve_local_binding

MODEL_ID = "model-01eb6a29a5c4d8edb30b"
MODEL_SHA = "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c"
PREPROCESS = "u2net-human-rgb320-lanczos-max-imagenet-native-L/1"


def prepare(
    source: Path,
    duration: float,
    settings: Settings,
    guard: Callable[..., None],
) -> dict[str, Any]:
    # Only the worker resolves the installed read-only model. Plans and creative
    # inputs cannot select model or cache paths.
    bindings = read_dependency_manifest(settings.video_editing_native_bindings_file)
    path = resolve_local_binding(
        settings.video_editing_native_bindings_file,
        bindings.get("resources", {}).get(MODEL_ID),
    )
    if not path or not Path(path).is_file() or sha256(Path(path)) != MODEL_SHA:
        raise ValueError("Installed presenter matte model is unavailable")
    source_sha = sha256(source)
    count = round(duration * 25)
    if count < 1 or not math.isfinite(duration):
        raise ValueError("Invalid foreground source duration")
    root = settings.video_editing_tasks_dir / "_foreground" / source_sha / MODEL_SHA
    root.mkdir(parents=True, exist_ok=True)
    receipt = root / "cache.json"
    cache: dict[str, Any] = (
        read_json(receipt)
        if receipt.is_file()
        else {
            "source_sha256": source_sha,
            "model_sha256": MODEL_SHA,
            "preprocessing": PREPROCESS,
            "fps": 25,
            "size": [1080, 1920],
            "frames": {},
        }
    )
    if any(
        cache.get(k) != v
        for k, v in {
            "source_sha256": source_sha,
            "model_sha256": MODEL_SHA,
            "preprocessing": PREPROCESS,
            "fps": 25,
            "size": [1080, 1920],
        }.items()
    ):
        raise ValueError("Foreground cache belongs to a different input")
    for row in cache["frames"].values():
        p = Path(row["path"])
        if (
            not p.resolve().is_relative_to(root.resolve())
            or not p.is_file()
            or sha256(p) != row["sha256"]
        ):
            raise ValueError("Source-bound foreground cache changed")
    missing = [n for n in range(count) if str(n) not in cache["frames"]]
    if not missing:
        return cache

    import cv2
    import numpy as np
    import onnxruntime as ort
    from PIL import Image

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
    capture = cv2.VideoCapture(str(source))
    if abs(capture.get(cv2.CAP_PROP_FPS) - 25) > 0.001:
        capture.release()
        raise ValueError("Native foreground clock requires the prepared25fps source")
    needed = set(missing)
    try:
        for n in range(count):
            ok, bgr = capture.read()
            if not ok:
                raise ValueError("Foreground source ended before its measured clock")
            if n not in needed:
                continue
            guard("preparing_foreground")
            im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            if im.size != (1080, 1920):
                raise ValueError("Prepared foreground source must be1080x1920")
            rgb: Any = np.asarray(
                im.resize((320, 320), Image.Resampling.LANCZOS), dtype=np.float32
            )
            rgb /= max(float(rgb.max()), 1)
            rgb = (rgb - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
                [0.229, 0.224, 0.225], np.float32
            )
            raw = session.run(
                None, {session.get_inputs()[0].name: rgb.transpose(2, 0, 1)[None]}
            )[0][0, 0]
            normalized = (raw - raw.min()) / max(float(raw.max() - raw.min()), 1e-8)
            mask = Image.fromarray(
                np.asarray(np.clip(normalized, 0, 1) * 255, dtype=np.uint8)
            ).resize(im.size, Image.Resampling.LANCZOS)
            target = root / f"f{n:06d}.png"
            temporary = root / f"f{n:06d}.pending.png"
            mask.save(temporary)
            temporary.replace(target)
            cache["frames"][str(n)] = {"path": str(target), "sha256": sha256(target)}
            if n % 16 == 0:
                atomic_json(receipt, cache)
    finally:
        capture.release()
        atomic_json(receipt, cache)
    if sha256(source) != source_sha:
        raise ValueError("Foreground source changed during preparation")
    return cache
