"""Per-frame layer timeline written next to a full-suite render.

Wraps the installed runtime's ``render_frame(cfg, n)`` for the duration of one
render. For every frame it records a digest of the composed RGB frame and, for
every returned RGBA role, its alpha bounding box, peak opacity and a content
signature (``layers-timeline.jsonl``). Overlay roles additionally get a coarse
content grid (mean opacity and premultiplied luma per ``CELL`` square), stored
sparsely whenever it changes (``layers-grid.npz``), so the quality checker can
see text revealed inside an already opaque card, not only alpha fades.

Recording never changes pixels; any recorder failure marks the timeline
incomplete instead of failing the render.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

VERSION = "bihuo-layer-timeline/2"
FILENAME = "layers-timeline.jsonl"
GRID_FILENAME = "layers-grid.npz"
CELL = 24
# The source picture, captions and static backgrounds are not overlay entries.
UNGRIDDED_ROLES = re.compile(r"presenter|caption|subtitle|background|stage|raw")


class Recorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.grids: dict[str, list[tuple[int, Any]]] = {}
        self.last: dict[str, bytes] = {}
        self.error: str | None = None

    def role(self, name: str, image: Any, n: int) -> dict[str, Any] | None:
        import numpy as np

        if getattr(image, "mode", None) != "RGBA":
            return None
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        peak = alpha.getextrema()[1] / 255 if bbox else 0.0
        row: dict[str, Any] = {
            "bbox": list(bbox) if bbox else None,
            "peak": round(peak, 4),
            "size": [image.width, image.height],
        }
        if UNGRIDDED_ROLES.search(name):
            row["sig"] = zlib.crc32(repr((bbox, peak)).encode())
            return row
        cells = np.asarray(image.reduce(CELL), dtype=np.uint16)
        luma = (cells[..., 0] * 77 + cells[..., 1] * 150 + cells[..., 2] * 29) >> 8
        grid = np.stack([cells[..., 3], luma * cells[..., 3] // 255], axis=-1).astype(
            np.uint8
        )
        raw = grid.tobytes()
        row["sig"] = zlib.crc32(raw) ^ zlib.crc32(repr(bbox).encode())
        if self.last.get(name) != raw:
            self.grids.setdefault(name, []).append((n, grid))
            self.last[name] = raw
        return row

    def frame(self, n: int, result: Any) -> None:
        if self.error:
            return
        try:
            rgb, roles = (
                result
                if isinstance(result, tuple) and len(result) == 2
                else (result, {})
            )
            row: dict[str, Any] = {
                "n": n,
                "rgb": hashlib.blake2b(rgb.tobytes(), digest_size=12).hexdigest(),
                "roles": {},
            }
            if isinstance(roles, dict):
                for name, image in roles.items():
                    entry = self.role(str(name), image, n)
                    if entry is not None:
                        row["roles"][str(name)] = entry
            self.rows.append(row)
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"[:300]

    def write(self, output: Path) -> dict[str, Any]:
        import numpy as np

        path = output / FILENAME
        with path.open("w", encoding="utf-8") as stream:
            for row in self.rows:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        arrays: dict[str, Any] = {"cell": np.array([CELL])}
        for index, (name, changes) in enumerate(sorted(self.grids.items())):
            arrays[f"name_{index}"] = np.array([name])
            arrays[f"frames_{index}"] = np.array([n for n, _ in changes])
            arrays[f"grids_{index}"] = np.stack([g for _, g in changes])
        grid_path = output / GRID_FILENAME
        np.savez_compressed(grid_path, **arrays)
        return {
            "version": VERSION,
            "file": FILENAME,
            "grid_file": GRID_FILENAME,
            "frames": len(self.rows),
            "complete": self.error is None,
            "error": self.error,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "grid_sha256": hashlib.sha256(grid_path.read_bytes()).hexdigest(),
        }


def load_grids(path: Path, frames: int) -> dict[str, Any]:
    """Dense ``[frames, rows, cols, 2]`` int16 grids, forward-filled per role."""
    import numpy as np

    data = np.load(path)
    result = {}
    index = 0
    while f"name_{index}" in data:
        name = str(data[f"name_{index}"][0])
        at = data[f"frames_{index}"]
        grids = data[f"grids_{index}"].astype(np.int16)
        dense = np.zeros((frames, *grids.shape[1:]), dtype=np.int16)
        for i, n in enumerate(at):
            stop = at[i + 1] if i + 1 < len(at) else frames
            dense[n:stop] = grids[i]
        result[name] = dense
        index += 1
    return result


@contextmanager
def recording(module: Any) -> Iterator[Recorder]:
    recorder = Recorder()
    original = getattr(module, "render_frame", None)
    if original is None:
        recorder.error = "runtime has no render_frame(cfg, n) entry point"
        yield recorder
        return

    @wraps(original)
    def recorded(cfg: Any, n: int, *args: Any, **kwargs: Any) -> Any:
        result = original(cfg, n, *args, **kwargs)
        recorder.frame(int(n), result)
        return result

    module.render_frame = recorded
    try:
        yield recorder
    finally:
        module.render_frame = original
