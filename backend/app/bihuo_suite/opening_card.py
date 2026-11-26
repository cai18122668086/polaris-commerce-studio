"""Opening title clear of the presenter window (``bihuo-opening-card/1``).

bihuo-02 (bundle fk-1104, kind ``capsule``) draws its opening card
(``back_card``, rows 390-819) *below* the presenter window, whose opening pose
starts at ``motion.from`` y=476, and writes the opening title at a fixed
y=461 (``core/capsule_engine.py`` line 171). A 34 px title spans rows ~462-493,
so the window hides about half of every character for the whole opening
(e2e 2026-11-26, plan section 2.2 "reverse occlusion").

The bundle is hash-locked, so the host rebuilds only that layer while the
opening lasts, with the same card, font, size, colour, x and fade, and the
title centred in the strip the window leaves visible (390 .. window top).
Nothing else changes; frames after the opening are untouched. It runs only
when the render config enables the phase-2 frame policy, so
``POLARIS_VIDEO_EDITING_FRAME_POLICY=off`` (or reverting this commit) restores
the template's original drawing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from . import frame_policy

VERSION = "bihuo-opening-card/1"
CARD = (54, 390, 1026, 819)
TITLE_X = 120
TITLE_SIZE = 34
TITLE_COLOR = (80, 80, 80, 255)
MIN_PAD = 6


def _engine(module: Any) -> Any | None:
    meta = getattr(module, "META", None)
    engine = getattr(module, "capsule", None)
    if not isinstance(meta, dict) or meta.get("kind") != "capsule" or engine is None:
        return None
    needed = ("render_layers", "text_at", "blank", "alpha", "ease")
    return engine if all(hasattr(engine, name) for name in needed) else None


class Record:
    def __init__(self) -> None:
        self.frames = 0
        self.skipped: str | None = None
        self.title_y: float | None = None
        self.original_y = 461

    def receipt(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "frames": self.frames,
            "title_y": self.title_y,
            "original_y": self.original_y,
            "skipped": self.skipped,
        }


def rebuild(engine: Any, cfg: dict, t: float, record: Record) -> Any | None:
    """The opening card with its title inside the visible strip, or None."""
    from PIL import ImageDraw

    title = cfg.get("opening_title")
    motion = cfg.get("motion") or {}
    if not title or t >= float(motion.get("times", [0])[0]):
        return None
    k = float(cfg["size"][0]) / 1080
    window_top = float(motion["from"][1]) * k
    probe = engine.blank(cfg)
    box = engine.text_at(
        probe, title, cfg["fonts"]["body"], TITLE_SIZE * k, 0, 0, TITLE_COLOR
    )
    height = box[3] - box[1]
    card_top = CARD[1] * k
    if record.original_y * k + height <= window_top:
        record.skipped = "title already clear of the window"
        return None
    if window_top - card_top < height + 2 * MIN_PAD * k:
        record.skipped = "visible strip too small for the title"
        return None
    y = card_top + (window_top - card_top - height) / 2
    back = engine.blank(cfg)
    draw = ImageDraw.Draw(back)
    draw.rounded_rectangle(tuple(v * k for v in CARD), radius=48 * k, fill="white")
    engine.text_at(
        back, title, cfg["fonts"]["body"], TITLE_SIZE * k, TITLE_X * k, y, TITLE_COLOR
    )
    record.title_y = round(y / k, 1)
    record.frames += 1
    # Same fade as the template: gone by the time the window starts moving.
    return engine.alpha(back, 1 - engine.ease(2.4, 2.6, t))


@contextmanager
def execution(module: Any, payload: dict[str, Any]) -> Iterator[Record | None]:
    engine = _engine(module)
    if engine is None or not frame_policy.enabled(payload):
        yield None
        return
    original = engine.render_layers
    record = Record()

    def render_layers(frame: Any, t: float, cfg: dict) -> dict:
        layers = original(frame, t, cfg)
        try:
            back = rebuild(engine, cfg, t, record)
        except Exception as error:  # never fail a render over this layer
            record.skipped = f"{type(error).__name__}: {error}"[:200]
            back = None
        if back is not None and isinstance(layers, dict) and "back_card" in layers:
            layers["back_card"] = back
        return layers

    engine.render_layers = render_layers
    try:
        yield record
    finally:
        engine.render_layers = original
