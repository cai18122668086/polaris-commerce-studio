"""Speech-led visual timing for full-suite renders (``bihuo-sync/1``).

Applied at compile time to the resolved plan only. Saved plans, recorded word
clocks, captions and the hash-pinned template bundles stay unchanged; the
policy version and every timing decision are recorded in the compiled config
and in the render receipt.

Rules (docs/video-editing-upgrade-plan-20261125.md, section 3.1):

1. A material starts with the first word of its matched phrase (``edge=start``),
   not at the word the planner picked inside the phrase. A long phrase
   (> 2.5 s) keeps a planner anchor that is a number or Latin name.
2. Visual elements lead the word by ``BASE_LEAD_S`` plus the time the template's
   own entry curve needs to reach 50% opacity, so the element is visibly
   present when the word starts. Times are floored to the 25 fps frame grid.
3. A material stays until the next material is visible (or the body ends),
   with at least ``MIN_DWELL_S`` on screen; materials never overlap.
4. Points, feature phrases and chapter entries get the same lead-in.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

VERSION = "bihuo-sync/1"
OFF = "off"
# Records sync targets without retiming (quality-check baselines only).
BASELINE = "baseline"
POLICIES = (VERSION, OFF, BASELINE)
FPS = 25
BASE_LEAD_S = 0.12
MIN_DWELL_S = 1.2
LONG_PHRASE_S = 2.5
DEFAULT_HALF_S = 0.10
# Seconds from an element's start time to 50% opacity under the template's own
# entry curve (cubic-out reaches 50% at 20.6% of its span, smoothstep and
# linear at 50%). Measured from the installed runtimes; see the plan doc.
MATERIAL_HALF_S: dict[str, float] = {
    "bihuo-02-v1": 0.066,  # V03 media: 8 frames cubic-out
    "bihuo-03-v1": 0.066,
    "bihuo-04-v1": 0.066,
    "bihuo-08-v1": 0.124,  # cubic-out 15 frames
    "bihuo-10-v1": 0.083,  # cubic-out 0.4 s
    "bihuo-11-v1": 0.18,  # linear 0.36 s
    "bihuo-13-v1": 0.198,  # cubic-out 24 frames
    "bihuo-14-v1": 0.14,  # smoothstep from -0.04 to +0.32
    "bihuo-16-v1": 0.16,  # linear 0.32 s
    "bihuo-19-v1": 0.16,
    "bihuo-23-v1": 0.14,
    "bihuo-24-v1": 0.165,  # cubic-out 20 frames
    "bihuo-26-v1": 0.16,
    "bihuo-27-v1": 0.083,
    "bihuo-28-v1": 0.10,  # smoothstep from -0.04 to +0.24
    "bihuo-33-v1": 0.16,
    "bihuo-40-v1": 0.16,
    "bihuo-47-v1": 0.24,  # smoothstep 0.48 s
    "bihuo-48-v1": 0.18,
}
POINT_HALF_S: dict[str, float] = {
    "bihuo-02-v1": 0.06,  # capsule list row: smoothstep 0.12 s
}
_KEEP_ANCHOR = re.compile(r"[0-9A-Za-z%]")


def floor_frame(seconds: float, fps: int = FPS) -> float:
    """Latest frame boundary at or before ``seconds`` (never rounds later)."""
    return math.floor(seconds * fps + 1e-6) / fps


def ceil_frame(seconds: float, fps: int = FPS) -> float:
    """Earliest frame boundary at or after ``seconds``."""
    return math.ceil(seconds * fps - 1e-6) / fps


def lead_seconds(template_id: str | None, kind: str) -> float:
    table = MATERIAL_HALF_S if kind == "material" else POINT_HALF_S
    half = table.get(template_id or "", DEFAULT_HALF_S)
    return max(0.0, BASE_LEAD_S + half)


def _token_text(resolved: dict[str, Any], token_id: str | None) -> str:
    for token in resolved.get("tokens") or []:
        if token.get("id") == token_id:
            return str(token.get("text", ""))
    return ""


def _token_start(resolved: dict[str, Any], token_id: str | None) -> float | None:
    for token in resolved.get("tokens") or []:
        if token.get("id") == token_id:
            return float(token["start_ms"]) / 1000
    return None


def _material_speech(resolved: dict[str, Any], material: dict[str, Any]) -> float:
    span = material.get("spoken_span") or {}
    start = float(span.get("start", material["start"]))
    end = float(span.get("end", material["end"]))
    if end - start > LONG_PHRASE_S and _KEEP_ANCHOR.search(
        _token_text(resolved, material.get("show_at_token_id"))
    ):
        anchored = _token_start(resolved, material.get("show_at_token_id"))
        if anchored is not None:
            return anchored
    return start


def _sequence(
    rows: list[dict[str, Any]],
    key: str,
    lead: float,
    floor: float,
    kind: str,
    enabled: bool,
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Lead each row; never before the previous phrase ends or the opening."""
    changed = []
    previous_end = floor
    previous_start = -math.inf
    for index, row in enumerate(rows):
        speech = float(row[key])
        visible = speech
        if enabled:
            lower = max(floor, previous_end, previous_start + 1 / FPS)
            visible = floor_frame(speech - lead)
            if visible < lower - 1e-9:
                visible = min(speech, ceil_frame(lower))
        targets.append(
            {
                "kind": kind,
                "index": index,
                "text": row.get("text", ""),
                "speech_start": speech,
                # The template reserves the opening for its title: nothing in
                # the body can be visible earlier, whatever the speech does.
                "allowed_start": max(speech, floor),
                "visible_start": visible,
                "lead_s": round(speech - visible, 6),
            }
        )
        previous_end = float(row.get("end", speech))
        previous_start = visible
        changed.append({**row, key: visible} if visible != speech else row)
    return changed


def apply(
    resolved: dict[str, Any], template_id: str | None, policy: str = VERSION
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the retimed resolved plan and the record for config/receipt."""
    if policy not in POLICIES:
        raise ValueError("Unknown visual sync policy")
    enabled = policy == VERSION
    result = deepcopy(resolved)
    opening = float(result.get("opening_end") or 0)
    targets: list[dict[str, Any]] = []

    materials = result.get("materials") or []
    lead = lead_seconds(template_id, "material")
    previous_visible = -math.inf
    for index, material in enumerate(materials):
        speech = _material_speech(result, material)
        visible = float(material["start"])
        if enabled:
            lower = max(opening, previous_visible + MIN_DWELL_S)
            visible = floor_frame(speech - lead)
            if visible < lower - 1e-9:
                visible = ceil_frame(lower)
            material.update(start=visible, edge="start")
        previous_visible = visible
        targets.append(
            {
                "kind": "material",
                "index": index,
                "asset_id": material.get("asset_id"),
                "text": material.get("spoken_text", ""),
                "speech_start": float(speech),
                "allowed_start": max(float(speech), opening),
                "visible_start": visible,
                "lead_s": round(float(speech) - visible, 6),
            }
        )
    if enabled:
        for current, following in zip(materials, materials[1:], strict=False):
            current["end"] = following["start"]
        # Material targets are recorded first, so targets[i] is material i.
        for index, material in enumerate(materials):
            if material["end"] <= material["start"]:
                # Only the last material can meet the body end this way.
                material["start"] = floor_frame(material["end"] - 1 / FPS)
                target = targets[index]
                target["visible_start"] = material["start"]
                target["lead_s"] = round(target["speech_start"] - material["start"], 6)
            span = material.get("spoken_span")
            if isinstance(span, dict):
                # Hold until the next material instead of vanishing at the
                # end of the sentence; the spoken text itself is unchanged.
                material["spoken_span"] = {**span, "end": material["end"]}

    point_lead = lead_seconds(template_id, "point")
    for name, kind in (("points", "point"), ("features", "feature")):
        rows = result.get(name) or []
        result[name] = _sequence(
            rows, "start", point_lead, opening, kind, enabled, targets
        )
    chapters = result.get("chapters") or []
    result["chapters"] = _sequence(
        chapters, "time", point_lead, 0.0, "chapter", enabled, targets
    )
    record = {
        "version": policy,
        "fps": FPS,
        "base_lead_s": BASE_LEAD_S,
        "min_dwell_s": MIN_DWELL_S,
        "material_lead_s": lead,
        "point_lead_s": point_lead,
        "targets": targets,
    }
    return (result if enabled else resolved), record
