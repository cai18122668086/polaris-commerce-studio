"""Give the original frame-index sampler a PTS-aligned presenter plate."""

import importlib
import math
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


def install_presenter_frame_clock(package: Path, root: Path) -> None:
    receipt_path = root / FRAME_CLOCK_RECEIPT
    if not receipt_path.is_file():
        return
    receipt = read_json(receipt_path)
    plate = (root / FRAME_CLOCK_PLATE).resolve()
    source = root / "input/source.mp4"
    if (
        receipt["version"] != FRAME_CLOCK_VERSION
        or not plate.is_relative_to(root)
        or sha256(plate) != receipt["plate_sha256"]
        or sha256(source) != receipt["source_sha256"]
        or sha256(package / _NATIVE_MEDIA) != _NATIVE_MEDIA_SHA256
    ):
        raise ValueError("Presenter clock or original sampler identity changed")
    episode = read_json(root / "episode.json")
    paths = {source.resolve()}
    paths.update(
        Path(row["path"]).resolve()
        for row in episode["production"]["materials"]
        if row["kind"] == "original_video" and row["sha256"] == receipt["source_sha256"]
    )
    sys.path[:0] = [str(package), str(package / _OWNER)]
    try:
        media: Any = importlib.import_module("unified.core.media")
    finally:
        del sys.path[:2]
    if Path(media.__file__).resolve() != package / _NATIVE_MEDIA:
        raise ValueError("Presenter clock requires its pinned original sampler")
    inspect_asset = media.inspect_asset

    @cache
    def verify_input(path: Path) -> None:
        if path != source and sha256(path) != receipt["source_sha256"]:
            raise ValueError("Presenter asset differs from the measured clock")

    def inspect_with_frame_clock(raw: dict, alpha_required: bool = False) -> Any:
        path = Path(raw["path"]).resolve()
        if path in paths and raw.get("kind", "auto") in {"video", "auto"}:
            verify_input(path)
            raw = {**raw, "path": str(plate)}
        return inspect_asset(raw, alpha_required)

    media.inspect_asset = inspect_with_frame_clock
