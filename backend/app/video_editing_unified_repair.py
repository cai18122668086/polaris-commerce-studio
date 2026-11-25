"""Repair unified-scene beats whose native inputs cannot compile (knowledge-talk).

The saved knowledge-talk response (e2e 2026-11-25, planning 2047ecb8) passed
semantic validation, but auto preview then failed with
EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED for Z-M03:

* Z-M03 and Z-M01 listed a project image in ``asset_ids`` although the scene
  has no image slot, so the image was never bound (asset set != bound media).
* Z-M03 filled one of its three label/event slots, Z-M14 two of three.

Unbound extra assets are released from the beat. A non-signature beat whose
required slots are still incomplete becomes a plain presenter beat (Z-M00)
with the same words, captions and clock, as long as another motion type
remains. An incomplete signature beat (Z-M03 here) cannot be replaced and now
fails at planning with the same error code instead of after "completed". The check
uses the same compiler entry as the preview, right after planning, so the
paid plan is accepted instead of failing at preview.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import ApiError
from .video_editing_contracts import SemanticPlan, Transcript

PRESENTER_PATH = "/media/presenter/path"


def _plain_beat(row: dict[str, Any], presenter: str) -> dict[str, Any]:
    first, last = row["first_token_id"], row["last_token_id"]
    return {
        **row,
        "group_id": "Z-M00",
        "native_text": [
            {
                "path": "/content/captions/0/text",
                "first_token_id": first,
                "last_token_id": last,
                "punctuation": "preserve",
            }
        ],
        "native_events": [
            {"path": "/content/captions/0/start", "token_id": first, "edge": "start"},
            {"path": "/content/captions/0/end", "token_id": last, "edge": "end"},
        ],
        "native_media": [{"path": PRESENTER_PATH, "asset_id": presenter}],
        "relation_items": [],
    }


def repair_unified_beats(
    raw: dict[str, Any],
    plan: SemanticPlan,
    package: Path,
    transcript: Transcript,
    asset_cards: list[dict[str, Any]],
    signature_group_ids: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from .motion_library import read_json
    from .video_editing_native_content import CHAPTER_GROUPS
    from .video_editing_overlay_recipes import _unified_entry
    from .video_editing_overlay_templates import MIN_OVERLAY_TYPES
    from .video_editing_unified_scenes import UNIFIED_SCENE_GROUPS

    targets = [
        i
        for i, beat in enumerate(plan.beats)
        if beat.group_id in UNIFIED_SCENE_GROUPS and beat.group_id not in CHAPTER_GROUPS
    ]
    if not targets:
        return raw, []
    groups = {g["id"]: g for g in read_json(package / "catalog/groups.json")["groups"]}
    changed = deepcopy(raw)
    repairs: list[dict[str, Any]] = []
    downgrade: list[int] = []
    for i in targets:
        beat = plan.beats[i]
        row = changed["beats"][i]
        bound = {anchor.asset_id for anchor in beat.native_media} | {
            asset for item in beat.relation_items for asset in item.asset_ids
        }
        extra = [asset for asset in beat.asset_ids if asset not in bound]
        candidate = beat
        if extra:
            candidate = beat.model_copy(
                update={"asset_ids": [a for a in beat.asset_ids if a in bound]}
            )
        try:
            _unified_entry(
                package, groups[beat.group_id], candidate, transcript, asset_cards
            )
        except ApiError as error:
            if error.code != "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED":
                raise
            if beat.group_id in signature_group_ids:
                # The style's own motion cannot be replaced by plain captions.
                # Fail now, at planning, instead of after "completed".
                raise
            downgrade.append(i)
            continue
        if extra:
            row["asset_ids"] = list(candidate.asset_ids)
            repairs.append(
                {
                    "kind": "unbound_scene_assets_released",
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "asset_ids": extra,
                }
            )
    if downgrade:
        remaining = {
            beat.group_id
            for i, beat in enumerate(plan.beats)
            if i not in downgrade and beat.group_id != "Z-M00"
        }
        if len(remaining) < MIN_OVERLAY_TYPES:
            return raw, []  # Nothing valid would remain: keep the strict failure.
        for i in downgrade:
            beat = plan.beats[i]
            presenter = next(
                (a.asset_id for a in beat.native_media if a.path == PRESENTER_PATH),
                None,
            )
            if presenter is None:
                return raw, []
            changed["beats"][i] = _plain_beat(changed["beats"][i], presenter)
            repairs.append(
                {
                    "kind": "incomplete_scene_to_plain_presenter",
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "reason": "native_slots_incomplete",
                }
            )
    return changed, repairs
