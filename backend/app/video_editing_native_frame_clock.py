"""Give the original frame-index sampler PTS-aligned video plates."""

import importlib
import math
import re
import sys
from fractions import Fraction
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from .motion_library import read_json, sha256

FRAME_CLOCK_RECEIPT = "presenter-frame-clock.json"
FRAME_CLOCK_PLATE = "input/presenter-cfr.mp4"
FRAME_CLOCK_VERSION = "presenter-frame-clock/1"
FRAME_CLOCK_FPS = 30
MATERIAL_CLOCK_RECEIPT = "material-frame-clocks.json"
MATERIAL_CLOCK_VERSION = "material-frame-clocks/1"
CLOCK_RECEIPTS = (FRAME_CLOCK_RECEIPT, MATERIAL_CLOCK_RECEIPT)
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_NATIVE_MEDIA = _OWNER / "unified/core/media.py"
_NATIVE_MEDIA_SHA256 = (
    "3838f78d7e7062bda2365ff870dc64cb02493567b90378e09bb220712bd49fdf"
)


def variable_frame_clock(
    frames: list[dict], time_base: str, average_rate: str
) -> tuple[int, bool]:
    step = Fraction(time_base)
    timestamps = [int(frame["best_effort_timestamp"]) for frame in frames]
    if not timestamps or step <= 0 or any(a >= b for a, b in pairwise(timestamps)):
        raise ValueError("Video presentation timestamps must increase")
    intervals = len(timestamps) - 1
    # Container ticks can round a constant cadence. Measure departure from
    # the whole clock so slow drift and balanced rate changes are visible.
    tolerance = max(1, math.ceil(Fraction(2, 1000) / step))
    span = timestamps[-1] - timestamps[0]
    try:
        fps = Fraction(average_rate)
    except (ValueError, ZeroDivisionError):
        return len(timestamps), True
    if fps <= 0 or abs(Fraction(span) - intervals / (step * fps)) > tolerance:
        return len(timestamps), True
    variable = any(
        abs((at - timestamps[0]) * intervals - i * span) > intervals * tolerance
        for i, at in enumerate(timestamps)
    )
    return len(timestamps), variable


def project_video_inputs(root: Path, episode: dict) -> dict[str, tuple[Path, str]]:
    inputs = {}
    directory = root / "input/materials"
    for row in episode["production"]["materials"]:
        if row["kind"] != "video" or row.get("source") != "project_upload":
            continue
        path, aid, digest = Path(row["path"]).resolve(), row["id"], row["sha256"]
        if (
            path.parent != directory
            or path.stem != aid
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Project video must be staged inside its editing attempt")
        inputs[aid] = (path, digest)
    return inputs


def material_clock_plate(root: Path, digest: str) -> Path:
    return root / "input/material-cfr" / f"{digest}.mp4"


def install_native_frame_clocks(package: Path, root: Path) -> None:
    presenter_path, material_path = (root / name for name in CLOCK_RECEIPTS)
    if not presenter_path.is_file() and not material_path.is_file():
        return
    episode = read_json(root / "episode.json")
    replacements: dict[Path, tuple[str, Path]] = {}

    @cache
    def verify_input(path: Path, digest: str) -> None:
        if sha256(path) != digest:
            raise ValueError("Video asset differs from its measured frame clock")

    def bind(source: Path, digest: str, plate: Path, receipt: dict) -> None:
        if (
            digest != receipt["source_sha256"]
            or not plate.resolve().is_relative_to(root)
            or sha256(plate) != receipt["plate_sha256"]
        ):
            raise ValueError("Video frame clock plate differs from its sealed input")
        verify_input(source, digest)
        replacements[source] = (digest, plate)

    if presenter_path.is_file():
        receipt = read_json(presenter_path)
        if receipt["version"] != FRAME_CLOCK_VERSION:
            raise ValueError("Unknown presenter frame clock version")
        digest = receipt["source_sha256"]
        plate = root / FRAME_CLOCK_PLATE
        source = (root / "input/source.mp4").resolve()
        bind(source, digest, plate, receipt)
        for row in episode["production"]["materials"]:
            if row["kind"] == "original_video" and row["sha256"] == digest:
                replacements[Path(row["path"]).resolve()] = (digest, plate)

    if material_path.is_file():
        receipt = read_json(material_path)
        if receipt["version"] != MATERIAL_CLOCK_VERSION:
            raise ValueError("Unknown project video frame clock version")
        inputs = project_video_inputs(root, episode)
        for aid, row in receipt["materials"].items():
            source, digest = inputs[aid]
            bind(source, digest, material_clock_plate(root, digest), row)

    if sha256(package / _NATIVE_MEDIA) != _NATIVE_MEDIA_SHA256:
        raise ValueError("Original video sampler identity changed")
    sys.path[:0] = [str(package), str(package / _OWNER)]
    try:
        media: Any = importlib.import_module("unified.core.media")
    finally:
        del sys.path[:2]
    if Path(media.__file__).resolve() != package / _NATIVE_MEDIA:
        raise ValueError("Video frame clocks require the pinned original sampler")
    inspect_asset = media.inspect_asset

    def inspect_with_frame_clock(raw: dict, alpha_required: bool = False) -> Any:
        path = Path(raw["path"]).resolve()
        if path in replacements and raw.get("kind", "auto") in {"video", "auto"}:
            digest, plate = replacements[path]
            verify_input(path, digest)
            raw = {**raw, "path": str(plate)}
        return inspect_asset(raw, alpha_required)

    media.inspect_asset = inspect_with_frame_clock
