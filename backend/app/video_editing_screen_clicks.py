"""Estimate clicks from visible recording feedback using a bounded local scan."""

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

_WIDTH = 960
_SAMPLE_HZ = 15
_MAX_SECONDS = 180
_DEBOUNCE_MS = 145
_MAX_CLICKS = 60


def detect_screen_clicks(
    path: Path, duration_ms: int, guard: Callable[[], None]
) -> list[dict]:
    """Find newly checked indicators and pointer-confirmed screen transitions."""
    capture = cv2.VideoCapture(str(path))
    clicks: list[dict] = []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or not 1 <= fps <= 300:
            return []
        frames = min(
            int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            round(fps * min(duration_ms / 1000, _MAX_SECONDS)),
        )
        stride = max(1, round(fps / _SAMPLE_HZ))
        known: set[tuple[int, int]] = set()
        candidates: dict[tuple[int, int], tuple[int, int]] = {}
        previous_gray = None
        previous_cursor = None
        stable_cursor = 0
        for frame_no in range(frames):
            if frame_no % stride:
                if not capture.grab():
                    break
                continue
            if frame_no % (stride * _SAMPLE_HZ) == 0:
                guard()
            ok, image = capture.read()
            if not ok:
                break
            height, width = image.shape[:2]
            image = cv2.resize(
                image,
                (_WIDTH, max(1, round(height * _WIDTH / width))),
                interpolation=cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            marker_mask = cv2.inRange(hsv, (33, 140, 125), (46, 255, 255))
            marker_mask = cv2.morphologyEx(
                marker_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
            )
            _, _, stats, centers = cv2.connectedComponentsWithStats(marker_mask)
            markers = set()
            pointers = []
            for (_, _, w, h, area), (cx, cy) in zip(
                stats[1:], centers[1:], strict=True
            ):
                if (
                    6 <= w <= 19
                    and 6 <= h <= 19
                    and 0.8 <= w / h <= 1.25
                    and area >= 0.68 * w * h
                ):
                    markers.add((round(cx / 5), round(cy / 5)))
                elif (
                    3 <= w <= 9
                    and 5 <= h <= 13
                    and 12 <= area <= 45
                    and hsv[int(cy), int(cx), 2] >= 230
                ):
                    pointers.append((round(cx), round(cy)))
            if frame_no == 0:
                known.update(markers)
            at = round(frame_no / fps * 1000)
            change = (
                cv2.absdiff(gray, previous_gray) >= 27
                if previous_gray is not None
                else np.zeros_like(gray, dtype=bool)
            )
            changed_fraction = float(change.mean())
            # Ignore batches of new markers revealed by page navigation or scrolling.
            if changed_fraction >= 0.018:
                known.update(markers)
            fresh = []
            possible: list[tuple[int, str]] = []
            for marker in sorted(markers):
                # Nearby keys cover an indicator's antialiasing across the grid.
                adjacent = {
                    (marker[0] + x, marker[1] + y)
                    for x in (-1, 0, 1)
                    for y in (-1, 0, 1)
                }
                if known & adjacent:
                    continue
                old = next((key for key in candidates if key in adjacent), marker)
                first, samples = candidates.pop(old, (at, 0))
                if samples >= 3:
                    known.add(marker)
                    fresh.append(first)
                else:
                    candidates[marker] = (first, samples + 1)
            if len(fresh) == 1 and len(markers - known) < 2:
                possible.extend((first, "selection_feedback") for first in fresh)
            candidates = {
                key: val for key, val in candidates.items() if at - val[0] < 360
            }
            cursor = None
            if len(pointers) == 1:
                (cursor,) = pointers
            elif previous_cursor in pointers:
                cursor = previous_cursor
            if (
                cursor
                and previous_cursor
                and np.linalg.norm(np.subtract(cursor, previous_cursor)) <= 5
            ):
                if stable_cursor >= 2 and previous_gray is not None:
                    x, y = cursor
                    if (
                        0.03 <= changed_fraction <= 0.32
                        and change[
                            max(0, y - 22) : y + 23, max(0, x - 22) : x + 23
                        ].mean()
                        >= 0.18
                    ):
                        possible.append((at, "pointer_state_change"))
                stable_cursor += 1
            else:
                stable_cursor = 0
            previous_gray = gray
            previous_cursor = cursor
            for when, evidence in sorted(possible):
                if when >= 160 and all(
                    abs(when - click["source_ms"]) >= _DEBOUNCE_MS for click in clicks
                ):
                    clicks.append({"source_ms": when, "evidence": evidence})
            if len(clicks) >= _MAX_CLICKS:
                break
        return sorted(clicks, key=lambda click: click["source_ms"])[:_MAX_CLICKS]
    finally:
        capture.release()
