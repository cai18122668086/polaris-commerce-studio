"""Presenter face detection for host-side layout safety.

The detector runs on the template's own presenter layer, so a face box is
already in output coordinates whatever crop, window or scale the template
applied to the source. Model: YuNet (OpenCV Zoo, MIT licence),
``face_detection_yunet_2023mar.onnx``, vendored and pinned by SHA-256 like the
other installed models; OpenCV 5's ``cv2.FaceDetectorYN`` runs it on CPU.

Detection never fails a render: an unavailable model or detector error yields
no face, and the caller records that the safety policy did not run.
"""

from __future__ import annotations

import hashlib
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
# Detect at a quarter of 1080x1920; a face in a small presenter window (about
# 100 px wide) is still 25 px, inside YuNet's working range.
SCALE = 4
SCORE = 0.6
NMS = 0.3

Box = tuple[int, int, int, int]


@lru_cache(maxsize=1)
def model_available() -> bool:
    try:
        return hashlib.sha256(MODEL.read_bytes()).hexdigest() == MODEL_SHA256
    except OSError:
        return False


class FaceDetector:
    """Largest confident face on an RGBA layer composited over black."""

    def __init__(self, size: tuple[int, int] = (1080, 1920), scale: int = SCALE):
        import cv2

        if not model_available():
            raise RuntimeError("Installed face model is unavailable")
        self.scale = scale
        self.small = (size[0] // scale, size[1] // scale)
        self.detector = cv2.FaceDetectorYN.create(
            str(MODEL), "", self.small, SCORE, NMS, 20
        )

    def detect(self, image: Any) -> tuple[Box, float] | None:
        import numpy as np

        small = image.reduce(self.scale)
        if small.size != self.small:
            small = small.resize(self.small)
        array = np.asarray(small, dtype=np.float32)
        if array.shape[-1] == 4:
            rgb = array[..., :3] * (array[..., 3:4] / 255.0)
        else:
            rgb = array[..., :3]
        bgr = np.ascontiguousarray(rgb[..., ::-1].astype(np.uint8))
        _, faces = self.detector.detect(bgr)
        if faces is None or not len(faces):
            return None
        best = max(faces, key=lambda row: float(row[2] * row[3] * row[-1]))
        x, y, w, h = (float(v) * self.scale for v in best[:4])
        return (round(x), round(y), round(x + w), round(y + h)), float(best[-1])


def expand(box: Box, left: float, top: float, right: float, bottom: float) -> Box:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    return (
        round(x0 - w * left),
        round(y0 - h * top),
        round(x1 + w * right),
        round(y1 + h * bottom),
    )


def union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


class FaceTrack:
    """Causal smoothing: the union of the detections in the last ``window``.

    A short miss (blink, turn, motion blur) keeps the last zone for ``hold``
    frames, so a card does not jump back over the face for one frame.
    """

    def __init__(self, window: int = 10, hold: int = 12):
        self.window = window
        self.hold = hold
        self.rows: deque[tuple[int, Box]] = deque()

    def update(self, n: int, box: Box | None) -> Box | None:
        if box is not None:
            self.rows.append((n, box))
        while self.rows and n - self.rows[0][0] >= self.window:
            if len(self.rows) == 1 and n - self.rows[0][0] < self.hold:
                break
            self.rows.popleft()
        if not self.rows or n - self.rows[-1][0] >= self.hold:
            return None
        # Only history that overlaps the latest face: when the template moves
        # the presenter (full screen -> small window) the old box is stale.
        latest = self.rows[-1][1]
        return union([box for _, box in self.rows if overlaps(box, latest)])


def overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
