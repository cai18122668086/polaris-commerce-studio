"""Host-side per-frame layout safety and transitions (``bihuo-frame/1``).

Applied while an installed full-suite runtime renders, around its own
``render_frame(cfg, n) -> (rgb, roles[, meta])``. Template files, saved plans
and word clocks stay unchanged; the policy version comes from the compiled
config (old configs without it render exactly as before) and every decision
is written to ``frame-policy.jsonl`` and the render receipt.

Rules (docs/video-editing-upgrade-plan-20261125.md, sections 3.2 and 3.3 P3;
owner decisions in 8.1):

1. Face safety. The face is detected on the template's presenter layer (so in
   output coordinates). Cards and captions drawn above the presenter must not
   cover it: a layer group that covers the face moves up or down to the
   nearest clear band (shrinking to at most 72% if needed), the whole group
   together, eased over a few frames. Captions only move as a caption group;
   a card never moves into the caption band. A full-screen layer (B-roll) may
   cover the face; its episodes are recorded (owner limit 2.5 s, enforced by
   the quality check).
2. Transitions. An overlay card layer that cuts hard (static, then replaced,
   shown or removed in one frame) dissolves over ``DISSOLVE_FRAMES`` instead.
   The presenter, its frame decorations and captions are never dissolved.
   When a switch only changes thin content on an unchanged card (text that
   moves or is replaced), a crossfade would show old and new text on top of
   each other; that switch instead fades the old text into the card and the
   new text out of it (``text-dip``), so the two are never visible together.
   A text-only layer without a shared card (sparse on a transparent layer)
   fades out completely before the new text fades in.

Only frames that change are recomposited:
``out = rgb + plain(adjusted roles) - plain(original roles)``, so a template
whose own compositor is not a plain alpha stack differs from it only inside
the adjusted region. Any policy error disables the policy for the rest of the
render and is recorded; it never fails the render.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from . import subject

VERSION = "bihuo-frame/1"
OFF = "off"
POLICIES = (VERSION, OFF)
FILENAME = "frame-policy.jsonl"
W, H = 1080, 1920

PRESENTER = re.compile(r"presenter|^raw$")
# Decorations that belong to the presenter window move with it, never alone.
PRESENTER_DECOR = re.compile(r"(presenter|window).*(border|glow|edge|shadow)|^frame$")
CAPTION = re.compile(r"caption|subtitle|^zh_|^en_")
BACKGROUND = re.compile(r"background|^stage")
# An overlay whose alpha box covers this share of the frame is a full-screen
# picture (B-roll), not a card: it is allowed over the face for a short time.
FULL_FRAME_SHARE = 0.6
BROLL_MAX_S = 2.5

# Face zones relative to the detected box: the core (eyes to chin plus a
# little forehead) triggers avoidance; placement keeps the wider safe zone
# (plan 3.2: +25%, and 15% more above for hair) clear when it can.
CORE = (0.10, 0.15, 0.10, 0.08)
SAFE = (0.25, 0.40, 0.25, 0.25)
COVER_TRIGGER = 0.03  # share of the core covered before a group moves
ROLE_TRIGGER = 0.01
MARGIN = 40
GAP = 16
# Layers this close belong to one card (title + support line) and move together.
GROUP_GAP = 56
SCALES = (1.0, 0.9, 0.8, 0.72)
SCALE_COST = 1200  # px of travel one full unit of shrink is worth
EASE_FRAMES = 6
SNAP_FRAMES = 3  # a group that just appeared takes its place without travel
RESET_FRAMES = 3
# A face moving faster than this (px per frame, centre, over SETTLE_FRAMES) is
# a designed presenter transition (full screen -> window): start no new move
# and do not retarget until it has settled, so cards never bounce mid-sweep.
FAST_PX = 6.0
SETTLE_FRAMES = 3

DISSOLVE_FRAMES = 4
# A switch whose changed pixels stay below this share of the layer's visible
# area is a text change on a card (text-dip); above it, a picture (crossfade).
TEXT_DIP_SHARE = 0.5
CHANGED_LEVEL = 24
# Text and line art are thin strokes: few of their opaque pixels survive a
# 9x9 erosion. Pictures and cards are solid (most pixels survive).
SOLID_SHARE = 0.3
# Weight of the card underneath the text per dissolve step, then of the new
# layer: out with the old text, one frame of bare card, in with the new text.
TEXT_DIP_STEPS = (("out", 0.5), ("out", 1.0), ("in", 0.5), ("in", 0.85))
CUT_DELTA = 0.08
STATIC_DELTA = 0.01
MIN_CUT_SHARE = 0.004
GRID = 8

Box = tuple[int, int, int, int]


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _cubic_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _area(box: Box | None) -> int:
    if not box:
        return 0
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersect(a: Box, b: Box) -> Box | None:
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return box if box[0] < box[2] and box[1] < box[3] else None


def _clip(box: Box) -> Box:
    return (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))


def _near(a: Box, b: Box, gap: int = GAP) -> bool:
    return not (
        a[2] + gap <= b[0]
        or b[2] + gap <= a[0]
        or a[3] + gap <= b[1]
        or b[3] + gap <= a[1]
    )


def coverage(image: Any, box: Box) -> float:
    """Mean opacity of ``image`` inside ``box`` (0..1)."""
    import numpy as np

    box = _clip(box)
    if not _area(box):
        return 0.0
    alpha = image.getchannel("A").crop(box)
    return float(np.asarray(alpha, dtype=np.float32).mean() / 255.0)


def union_coverage(images: list[Any], box: Box) -> float:
    import numpy as np

    box = _clip(box)
    if not images or not _area(box):
        return 0.0
    clear = None
    for image in images:
        a = np.asarray(image.getchannel("A").crop(box), dtype=np.float32) / 255.0
        clear = 1 - a if clear is None else clear * (1 - a)
    assert clear is not None
    return float(1 - clear.mean())


def transform_box(box: Box, anchor: tuple[float, float], s: float, dy: float) -> Box:
    ax, ay = anchor
    return (
        round(ax + (box[0] - ax) * s),
        round(ay + (box[1] - ay) * s + dy),
        round(ax + (box[2] - ax) * s),
        round(ay + (box[3] - ay) * s + dy),
    )


def transform_layer(
    image: Any, anchor: tuple[float, float], s: float, dy: float
) -> Any:
    from PIL import Image

    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    part = image.crop(bbox)
    target = transform_box(bbox, anchor, s, dy)
    if abs(s - 1) > 1e-6:
        size = (max(1, target[2] - target[0]), max(1, target[3] - target[1]))
        part = part.resize(size, Image.Resampling.LANCZOS)
    out.paste(part, (target[0], target[1]))
    return out


def place(
    box: Box,
    core: Box,
    safe: Box,
    top: int,
    bottom: int,
    obstacles: tuple[Box, ...] = (),
) -> tuple[float, float, str] | None:
    """Smallest move (and shrink) that clears ``safe`` (else ``core``).

    The moved card never lands on another visible card (``obstacles``), so a
    support line cannot jump above its own title.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for zone, label in ((safe, "safe"), (core, "core")):
        best: tuple[float, float, float] | None = None
        for s in SCALES:
            w, h = (x1 - x0) * s, (y1 - y0) * s
            left, right = cx - w / 2, cx + w / 2
            clear_x = right <= zone[0] or left >= zone[2]
            centres = {cy} if clear_x else set()
            for edge in (zone, *obstacles):
                centres.add(edge[1] - GAP - h / 2)
                centres.add(edge[3] + GAP + h / 2)
            for centre in centres:
                new = (left, centre - h / 2, right, centre + h / 2)
                if new[1] < top - 1 or new[3] > bottom + 1:
                    continue
                if not clear_x and not (new[3] <= zone[1] or new[1] >= zone[3]):
                    continue
                if any(
                    _near(tuple(round(v) for v in new), ob, GAP // 2)  # type: ignore[arg-type]
                    for ob in obstacles
                ):
                    continue
                if not _keeps_order(box, new, obstacles):
                    continue
                dy = centre - cy
                cost = abs(dy) + (1 - s) * SCALE_COST
                if best is None or cost < best[0]:
                    best = (cost, s, dy)
        if best is not None:
            return best[1], best[2], label
    return None


def _keeps_order(
    old: Box, new: tuple[float, float, float, float], obstacles: tuple[Box, ...]
) -> bool:
    """A card stays above (or below) every card it was above (or below)."""
    for ob in obstacles:
        if new[2] <= ob[0] or new[0] >= ob[2]:
            continue
        was_above = (old[1] + old[3]) / 2 < (ob[1] + ob[3]) / 2
        is_above = (new[1] + new[3]) / 2 < (ob[1] + ob[3]) / 2
        if was_above != is_above:
            return False
    return True


def _premultiplied_small(image: Any) -> Any:
    import numpy as np

    small = np.asarray(image.reduce(GRID), dtype=np.float32) / 255.0
    return np.concatenate([small[..., :3] * small[..., 3:4], small[..., 3:4]], axis=-1)


def _blend(a: Any, b: Any, w: float) -> Any:
    """Premultiplied mix of two RGBA layers (``w`` = weight of ``b``)."""
    import numpy as np
    from PIL import Image

    boxes = [x.getchannel("A").getbbox() for x in (a, b)]
    boxes = [x for x in boxes if x]
    if not boxes:
        return b
    region = subject.union(boxes)
    pa = np.asarray(a.crop(region), dtype=np.float32) / 255.0
    pb = np.asarray(b.crop(region), dtype=np.float32) / 255.0
    ca = pa[..., :3] * pa[..., 3:4]
    cb = pb[..., :3] * pb[..., 3:4]
    alpha = pa[..., 3:4] * (1 - w) + pb[..., 3:4] * w
    color = ca * (1 - w) + cb * w
    rgb = np.where(alpha > 1e-6, color / np.maximum(alpha, 1e-6), 0)
    out = np.concatenate([rgb, alpha], axis=-1)
    patch = Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")
    result = Image.new("RGBA", b.size, (0, 0, 0, 0))
    result.paste(patch, region[:2])
    return result


def _text_dip_base(a: Any, b: Any) -> Any | None:
    """What the old content dips into before the new one appears, or None.

    * Text changing on a card both layers share: the new layer with the
      changed pixels painted out (the bare card).
    * Text-only layers (sparse, no card): an empty layer, so the old text is
      gone before the new text appears.
    None means a picture or a large change: keep the plain crossfade.
    """
    import cv2
    import numpy as np
    from PIL import Image

    pa = np.asarray(a, dtype=np.int16)
    pb = np.asarray(b, dtype=np.int16)
    opaque_a, opaque_b = pa[..., 3] > 8, pb[..., 3] > 8
    if not opaque_a.any() or not opaque_b.any():
        return None
    changed = np.abs(pa - pb).max(axis=2) > CHANGED_LEVEL
    if not changed.any():
        return None

    def solid(opaque: Any) -> float:
        core = cv2.erode(opaque.astype(np.uint8), np.ones((9, 9), np.uint8))
        return float(core.sum()) / float(opaque.sum())

    visible = opaque_a & opaque_b
    if (changed & ~visible).any() or changed.sum() > TEXT_DIP_SHARE * visible.sum():
        if solid(opaque_a) < SOLID_SHARE and solid(opaque_b) < SOLID_SHARE:
            return Image.new("RGBA", b.size, (0, 0, 0, 0))
        return None
    ys, xs = np.nonzero(changed)
    pad = 12
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1, y1 = min(W, int(xs.max()) + pad + 1), min(H, int(ys.max()) + pad + 1)
    mask = cv2.dilate(
        changed[y0:y1, x0:x1].astype(np.uint8) * 255, np.ones((5, 5), np.uint8)
    )
    patch = np.asarray(b, dtype=np.uint8)[y0:y1, x0:x1]
    rgb = cv2.inpaint(np.ascontiguousarray(patch[..., :3]), mask, 5, cv2.INPAINT_TELEA)
    alpha = cv2.inpaint(np.ascontiguousarray(patch[..., 3]), mask, 5, cv2.INPAINT_TELEA)
    base = b.copy()
    base.paste(Image.fromarray(np.dstack([rgb, alpha]), "RGBA"), (x0, y0))
    return base


def _plain(roles: dict[str, Any]) -> Any:
    import numpy as np
    from PIL import Image

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for image in roles.values():
        if getattr(image, "mode", None) == "RGBA" and image.size == (W, H):
            canvas.alpha_composite(image)
    return np.asarray(canvas.convert("RGB"), dtype=np.int16)


class Policy:
    def __init__(self, fps: int = 25) -> None:
        self.fps = fps
        self.detector: subject.FaceDetector | None = None
        self.track = subject.FaceTrack()
        self.error: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.state: dict[str, dict[str, Any]] = {}
        self.seen: dict[str, int] = {}
        self.first_seen: dict[str, int] = {}
        self.prev_small: dict[str, Any] = {}
        self.prev_delta: dict[str, float] = {}
        self.prev_image: dict[str, Any] = {}
        self.prev_order: list[str] = []
        self.dissolves: dict[str, dict[str, Any]] = {}
        self.broll: dict[str, int] = {}
        self.easing: set[str] = set()
        self.centres: list[tuple[int, float, float]] = []
        self.frames_seen = 0
        self.summary: dict[str, Any] = {
            "face_frames": 0,
            "presenter_frames": 0,
            "moved_frames": 0,
            "moves": [],
            "unresolved": 0,
            "broll": [],
            "dissolves": {"switch": 0, "appear": 0, "disappear": 0},
            "text_dips": 0,
            "recomposited_frames": 0,
        }
        if subject.model_available():
            try:
                self.detector = subject.FaceDetector((W, H))
            except Exception as error:  # pragma: no cover - environment
                self.error = f"face detector: {type(error).__name__}: {error}"[:300]
        else:
            self.error = "face model unavailable"

    # -- face safety -----------------------------------------------------
    def _face(self, n: int, roles: dict[str, Any], presenters: list[str]) -> Box | None:
        if self.detector is None:
            return None
        from PIL import Image

        if len(presenters) == 1:
            layer = roles[presenters[0]]
        else:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for name in presenters:
                layer.alpha_composite(roles[name])
        found = self.detector.detect(layer)
        return found[0] if found else None

    def _groups(self, names: list[str], boxes: dict[str, Box]) -> list[list[str]]:
        parent = {name: name for name in names}

        def root(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                same_kind = bool(CAPTION.search(a)) == bool(CAPTION.search(b))
                if same_kind and _near(boxes[a], boxes[b], GROUP_GAP):
                    parent[root(a)] = root(b)
        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(root(name), []).append(name)
        return list(groups.values())

    def _sweeping(self, n: int) -> bool:
        rows = [r for r in self.centres if n - r[0] <= SETTLE_FRAMES]
        if len(rows) < 2:
            return False
        (n0, x0, y0), (n1, x1, y1) = rows[0], rows[-1]
        if n1 == n0:
            return False
        speed = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / (n1 - n0)
        return speed > FAST_PX

    def _current(self, st: dict[str, Any], n: int) -> tuple[float, float]:
        k = _ease((n - st["since"] + 1) / (EASE_FRAMES + 1))
        s = st["from_s"] + (st["s"] - st["from_s"]) * k
        dy = st["from_dy"] + (st["dy"] - st["from_dy"]) * k
        return s, dy

    def face_safety(
        self, n: int, roles: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        self.easing = set()
        names = list(roles)
        presenters = [
            k
            for k in names
            if PRESENTER.search(k)
            and not PRESENTER_DECOR.search(k)
            and getattr(roles[k], "mode", None) == "RGBA"
            and roles[k].size == (W, H)
        ]
        if not presenters:
            return roles
        top_presenter = max(names.index(k) for k in presenters)
        presenter_box = None
        for k in presenters:
            bb = roles[k].getchannel("A").getbbox()
            if bb:
                presenter_box = (
                    bb if presenter_box is None else subject.union([presenter_box, bb])
                )
        if presenter_box is None:
            return roles
        self.summary["presenter_frames"] += 1
        face = self._face(n, roles, presenters)
        zone = self.track.update(n, face)
        row["face"] = list(face) if face else None
        if face:
            self.centres.append((n, (face[0] + face[2]) / 2, (face[1] + face[3]) / 2))
            self.centres = self.centres[-(SETTLE_FRAMES + 1) :]
        sweeping = self._sweeping(n)
        if sweeping:
            row["sweeping"] = True
        if face:
            self.summary["face_frames"] += 1
        if zone is None:
            return roles
        # A face cannot extend past the presenter's own window.
        core_box = _intersect(_clip(subject.expand(zone, *CORE)), presenter_box)
        safe_box = _intersect(_clip(subject.expand(zone, *SAFE)), presenter_box)
        if core_box is None or safe_box is None:
            return roles
        core, safe = core_box, safe_box
        row["core"], row["safe"] = list(core), list(safe)

        boxes: dict[str, Box] = {}
        overlays: list[str] = []
        for k in names[top_presenter + 1 :]:
            image = roles[k]
            if (
                getattr(image, "mode", None) != "RGBA"
                or image.size != (W, H)
                or PRESENTER_DECOR.search(k)
                or BACKGROUND.search(k)
            ):
                continue
            bb = image.getchannel("A").getbbox()
            if not bb:
                continue
            boxes[k] = bb
            overlays.append(k)
            self.seen[k] = n
            self.first_seen.setdefault(k, n)

        # Full-screen pictures may cover the face briefly (owner: <= 2.5 s).
        full = [k for k in overlays if _area(boxes[k]) >= FULL_FRAME_SHARE * W * H]
        for k in full:
            cover = coverage(roles[k], core)
            if cover > COVER_TRIGGER:
                self.broll.setdefault(k, n)
            elif k in self.broll:
                self._close_broll(k, n)
        for k in list(self.broll):
            if k not in full:
                self._close_broll(k, n)
        movable = [k for k in overlays if k not in full]
        for k in list(self.state):
            if n - self.seen.get(k, -10) >= RESET_FRAMES:
                self.state.pop(k, None)
        for k in list(self.first_seen):
            if n - self.seen.get(k, -10) >= RESET_FRAMES:
                self.first_seen.pop(k, None)
        if not movable:
            return roles

        captions = [k for k in movable if CAPTION.search(k)]
        caption_box = subject.union([boxes[k] for k in captions]) if captions else None
        adjusted = dict(roles)
        for group in self._groups(movable, boxes):
            members_state = [self.state[k] for k in group if k in self.state]
            gbox = subject.union([boxes[k] for k in group])
            is_caption = bool(CAPTION.search(group[0]))
            bottom = H - MARGIN
            if not is_caption and caption_box and caption_box[1] >= core[3]:
                bottom = min(bottom, caption_box[1] - GAP)
            obstacles = tuple(boxes[k] for k in movable if k not in group)
            covered = union_coverage([roles[k] for k in group], core)
            st = max(members_state, key=lambda x: x["area"]) if members_state else None
            if st is not None:
                s_now, dy_now = self._current(st, n)
                moved = transform_box(gbox, st["anchor"], st["s"], st["dy"])
                clear = _intersect(moved, core) is None
                if not clear:
                    shifted = [
                        transform_layer(roles[k], st["anchor"], st["s"], st["dy"])
                        for k in group
                    ]
                    clear = union_coverage(shifted, core) <= COVER_TRIGGER
                if not clear and not sweeping:
                    st = self._retarget(
                        n,
                        group,
                        gbox,
                        core,
                        safe,
                        bottom,
                        obstacles,
                        st,
                        (s_now, dy_now),
                    )
            elif covered > COVER_TRIGGER and not sweeping:
                offenders = [
                    k for k in group if coverage(roles[k], core) > ROLE_TRIGGER
                ]
                if offenders:
                    st = self._retarget(
                        n, group, gbox, core, safe, bottom, obstacles, None, (1.0, 0.0)
                    )
            if st is None:
                continue
            for k in group:
                self.state[k] = st
            s_now, dy_now = self._current(st, n)
            if (s_now, dy_now) != (st["s"], st["dy"]):
                self.easing.update(group)
            if abs(s_now - 1) < 1e-6 and abs(dy_now) < 0.5:
                continue
            for k in group:
                adjusted[k] = transform_layer(roles[k], st["anchor"], s_now, dy_now)
            row.setdefault("moves", {})["+".join(sorted(group))] = [
                round(dy_now, 1),
                round(s_now, 3),
            ]
        if "moves" in row:
            self.summary["moved_frames"] += 1
        return adjusted

    def _retarget(
        self,
        n: int,
        group: list[str],
        gbox: Box,
        core: Box,
        safe: Box,
        bottom: int,
        obstacles: tuple[Box, ...],
        old: dict[str, Any] | None,
        now: tuple[float, float],
    ) -> dict[str, Any]:
        found = place(gbox, core, safe, MARGIN, bottom, obstacles)
        result = "clear"
        if found is None:
            # No clear band: smallest size, on the side with more room.
            s = SCALES[-1]
            h = (gbox[3] - gbox[1]) * s
            cy = (gbox[1] + gbox[3]) / 2
            room_above = core[1] - MARGIN
            room_below = bottom - core[3]
            if room_above >= room_below:
                dy = MARGIN + h / 2 - cy
            else:
                dy = bottom - h / 2 - cy
            found = (s, dy, "partial")
            result = "unresolved"
            self.summary["unresolved"] += 1
        s, dy, zone = found
        appeared = min(self.first_seen.get(k, n) for k in group)
        snap = n - appeared < SNAP_FRAMES
        st: dict[str, Any] = {
            "anchor": ((gbox[0] + gbox[2]) / 2, (gbox[1] + gbox[3]) / 2),
            "s": s,
            "dy": dy,
            "from_s": s if snap else now[0],
            "from_dy": dy if snap else now[1],
            "since": n,
            "area": _area(gbox),
        }
        if old is not None and not snap:
            # Travel continues from where the group is drawn now: express the
            # current position relative to the new anchor (the group centre).
            cy = (gbox[1] + gbox[3]) / 2
            ay = old["anchor"][1]
            st["from_dy"] = ay + (cy - ay) * now[0] + now[1] - cy
        self.summary["moves"].append(
            {
                "frame": n,
                "roles": sorted(group),
                "dy": round(dy, 1),
                "scale": s,
                "zone": zone,
                "result": result,
                "eased": not snap,
            }
        )
        return st

    def _close_broll(self, k: str, n: int) -> None:
        start = self.broll.pop(k)
        seconds = (n - start) / self.fps
        self.summary["broll"].append(
            {
                "role": k,
                "start_frame": start,
                "end_frame": n,
                "seconds": round(seconds, 3),
                "within_limit": seconds <= BROLL_MAX_S + 1e-9,
            }
        )

    # -- transitions -----------------------------------------------------
    def transitions(
        self, n: int, roles: dict[str, Any], row: dict[str, Any], moving: set[str]
    ) -> dict[str, Any]:
        import numpy as np
        from PIL import Image

        out = dict(roles)
        names = list(roles)
        candidates = [
            k
            for k in set(names) | set(self.prev_image)
            if not PRESENTER.search(k)
            and not PRESENTER_DECOR.search(k)
            and not CAPTION.search(k)
            and not BACKGROUND.search(k)
        ]
        blank = None
        for k in sorted(candidates):
            image = roles.get(k)
            if image is not None and (
                getattr(image, "mode", None) != "RGBA" or image.size != (W, H)
            ):
                continue
            if image is None:
                if blank is None:
                    blank = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                image = blank
            small = _premultiplied_small(image)
            prev = self.prev_small.get(k)
            if prev is None and self.frames_seen:
                prev = np.zeros_like(small)  # first appearance after frame 0
            delta = 0.0
            kind = None
            if prev is not None and k not in moving:
                mask = (prev[..., 3] > 0.02) | (small[..., 3] > 0.02)
                share = float(mask.mean())
                if share >= MIN_CUT_SHARE:
                    delta = float(np.abs(small - prev)[mask].mean())
                    was_static = self.prev_delta.get(k, 0.0) <= STATIC_DELTA
                    if delta >= CUT_DELTA and was_static:
                        had = float(prev[..., 3].max()) > 0.02
                        has = float(small[..., 3].max()) > 0.02
                        if had and has:
                            kind = "switch"
                        elif has and float(small[..., 3].max()) >= 0.85:
                            kind = "appear"
                        elif had and not has:
                            kind = "disappear"
            self.prev_delta[k] = delta
            self.prev_small[k] = small
            if kind and k not in self.dissolves:
                start = self.prev_image.get(k) or Image.new(
                    "RGBA", (W, H), (0, 0, 0, 0)
                )
                self.dissolves[k] = {"from": start, "since": n, "kind": kind}
                self.summary["dissolves"][kind] += 1
                row.setdefault("dissolves", []).append([k, kind])
                if kind == "switch":
                    base = _text_dip_base(start, image)
                    if base is not None:
                        self.dissolves[k]["base"] = base
                        self.summary["text_dips"] += 1
                        row.setdefault("text_dips", []).append(k)
            state = self.dissolves.get(k)
            shown = image
            if state is not None:
                step = n - state["since"]
                if step >= DISSOLVE_FRAMES:
                    self.dissolves.pop(k, None)
                elif "base" in state:
                    phase, w = TEXT_DIP_STEPS[step]
                    if phase == "out":
                        shown = _blend(state["from"], state["base"], w)
                    else:
                        shown = _blend(state["base"], image, w)
                else:
                    w = _cubic_out((step + 1) / (DISSOLVE_FRAMES + 1))
                    shown = _blend(state["from"], image, w)
            if image is blank and state is None:
                self.prev_image.pop(k, None)
                continue
            self.prev_image[k] = shown
            if shown is not image or k not in out:
                if k not in out:
                    out = self._insert(out, k, shown)
                else:
                    out[k] = shown
        self.prev_order = list(out)
        return out

    def _insert(self, roles: dict[str, Any], key: str, image: Any) -> dict[str, Any]:
        order = self.prev_order
        before = None
        if key in order:
            for name in reversed(order[: order.index(key)]):
                if name in roles:
                    before = name
                    break
        result: dict[str, Any] = {}
        if before is None:
            result[key] = image
        for name, value in roles.items():
            result[name] = value
            if name == before:
                result[key] = image
        return result

    # -- frame -----------------------------------------------------------
    def frame(self, n: int, result: Any) -> Any:
        import numpy as np
        from PIL import Image

        if self.error and self.error != "face model unavailable":
            return result
        if not (isinstance(result, tuple) and len(result) >= 2):
            return result
        rgb, roles = result[0], result[1]
        if not isinstance(roles, dict):
            return result
        row: dict[str, Any] = {"n": n}
        try:
            adjusted = self.face_safety(n, roles, row)
            adjusted = self.transitions(n, adjusted, row, self.easing)
            changed = adjusted.keys() != roles.keys() or any(
                adjusted[k] is not roles[k] for k in roles
            )
            if changed:
                base = np.asarray(rgb.convert("RGB"), dtype=np.int16)
                out = base + _plain(adjusted) - _plain(roles)
                rgb = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
                self.summary["recomposited_frames"] += 1
                row["recomposited"] = True
            self.rows.append(row)
            self.frames_seen += 1
            if changed:
                return (rgb, adjusted, *result[2:])
            return result
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"[:300]
            return result

    def finish(self, n_end: int) -> None:
        for k in list(self.broll):
            self._close_broll(k, n_end)

    def write(self, output: Path) -> dict[str, Any]:
        import hashlib

        self.finish(len(self.rows))
        path = output / FILENAME
        with path.open("w", encoding="utf-8") as stream:
            for row in self.rows:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        summary = dict(self.summary)
        summary["moves"] = summary["moves"][:200]
        return {
            "version": VERSION,
            "file": FILENAME,
            "frames": len(self.rows),
            "face_model_sha256": subject.MODEL_SHA256 if self.detector else None,
            "complete": self.error is None,
            "error": self.error,
            "broll_max_s": BROLL_MAX_S,
            "broll_over_limit": sum(
                1 for b in summary["broll"] if not b["within_limit"]
            ),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **summary,
        }


def enabled(payload: dict[str, Any]) -> bool:
    config = payload.get("config") if isinstance(payload, dict) else None
    policy = (config or {}).get("frame_policy") or {}
    return isinstance(policy, dict) and policy.get("version") == VERSION


@contextmanager
def execution(module: Any, payload: dict[str, Any]) -> Iterator[Policy | None]:
    original = getattr(module, "render_frame", None)
    if original is None or not enabled(payload):
        yield None
        return
    policy = Policy(int((payload.get("config") or {}).get("fps") or 25))

    @wraps(original)
    def guarded(cfg: Any, n: int, *args: Any, **kwargs: Any) -> Any:
        return policy.frame(int(n), original(cfg, n, *args, **kwargs))

    module.render_frame = guarded
    try:
        yield policy
    finally:
        module.render_frame = original


def unsupported(payload: dict[str, Any], module: Any) -> dict[str, Any] | None:
    """Receipt entry when the policy was requested but could not wrap."""
    if enabled(payload) and getattr(module, "render_frame", None) is None:
        return {
            "version": VERSION,
            "complete": False,
            "error": "runtime has no render_frame",
        }
    return None
