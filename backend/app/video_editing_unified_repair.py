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
remains. An incomplete signature beat (Z-M03 here) is replaced the same way only
when enough complete signature scenes remain; otherwise it fails at planning
with the same error code, naming the empty fixed slots, instead of after
"completed". List slots a beat's own relation_items already declare are bound
to those words first (a binding omission, not a missing item). The check
uses the same compiler entry as the preview, right after planning, so the
paid plan is accepted instead of failing at preview.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import ApiError
from .video_editing_contracts import SemanticBeat, SemanticPlan, Transcript

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


def _complete_declared_slots(row: dict[str, Any], beat: SemanticBeat) -> list[str]:
    """Bind list slots that the beat's own relation_items already declare.

    A relation item that names ``/content/labels/1`` with its recorded word
    range, while ``native_text`` omits that path, is a binding omission, not
    a missing item: bind the path to the item's words and add the paired
    entrance event at its first word. Nothing is invented: no relation item,
    no completion.
    """
    from .video_editing_unified_scenes import _LIST_SLOT, event_for_text

    text = {anchor.path for anchor in beat.native_text}
    events = {anchor.path for anchor in beat.native_events}
    added: list[str] = []
    for item in beat.relation_items:
        for path in item.native_text_paths:
            if path in text or not _LIST_SLOT.match(path):
                continue
            row.setdefault("native_text", []).append(
                {
                    "path": path,
                    "first_token_id": item.first_token_id,
                    "last_token_id": item.last_token_id,
                    "punctuation": "preserve",
                }
            )
            text.add(path)
            added.append(path)
            event = event_for_text(beat.group_id, path)
            if event and event not in events:
                row.setdefault("native_events", []).append(
                    {"path": event, "token_id": item.first_token_id, "edge": "start"}
                )
                events.add(event)
                added.append(event)
    return added


def _slot_gaps(package: Path, group: dict, beat: SemanticBeat) -> list[str]:
    from .motion_parameter_contracts import input_contract
    from .video_editing_unified_scenes import (
        UNIFIED_VIDEO_VARIANTS,
        missing_native_slots,
    )

    try:
        contract = input_contract(
            package,
            group,
            current_unified_presenter=beat.group_id in UNIFIED_VIDEO_VARIANTS,
        )
        return missing_native_slots(beat, contract)
    except Exception:  # noqa: BLE001 - diagnostics only; the compiler decides.
        return []


def repair_unified_beats(
    raw: dict[str, Any],
    plan: SemanticPlan,
    package: Path,
    transcript: Transcript,
    asset_cards: list[dict[str, Any]],
    signature_group_ids: set[str] | frozenset[str] = frozenset(),
    minimum_signature_occurrences: int = 1,
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
    incomplete_signature: list[tuple[int, list[str]]] = []
    complete_signature = sum(
        1
        for beat in plan.beats
        if beat.group_id in signature_group_ids
        and (
            beat.group_id not in UNIFIED_SCENE_GROUPS or beat.group_id in CHAPTER_GROUPS
        )
    )
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
        completed_row = deepcopy(row)
        completed = _complete_declared_slots(completed_row, candidate)
        if completed:
            candidate = SemanticBeat.model_validate(
                {**completed_row, "asset_ids": list(candidate.asset_ids)}
            )
        try:
            _unified_entry(
                package, groups[beat.group_id], candidate, transcript, asset_cards
            )
        except ApiError as error:
            if error.code != "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED":
                raise
            if beat.group_id in signature_group_ids:
                incomplete_signature.append(
                    (i, _slot_gaps(package, groups[beat.group_id], beat))
                )
            else:
                downgrade.append(i)
            continue
        if beat.group_id in signature_group_ids:
            complete_signature += 1
        if completed:
            row["native_text"] = completed_row["native_text"]
            row["native_events"] = completed_row["native_events"]
            repairs.append(
                {
                    "kind": "declared_relation_slots_bound",
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "paths": completed,
                }
            )
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
    if incomplete_signature:
        if complete_signature < max(1, minimum_signature_occurrences):
            # The style's own motion cannot be replaced by plain captions.
            # Fail now, at planning, instead of after "completed", and say
            # which fixed slots the response left empty.
            i, gaps = incomplete_signature[0]
            beat = plan.beats[i]
            detail = "、".join(gaps[:6]) if gaps else "原生字段"
            raise ApiError(
                422,
                "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED",
                f"招牌组 {beat.group_id}（{beat.id}）的固定槽位未填满：缺 {detail}。"
                "实录需有满足全部槽位数量的一段才能使用本款风格。",
            )
        # Enough complete signature scenes remain: plain presenter for the rest.
        downgrade.extend(i for i, _ in incomplete_signature)
        downgrade.sort()
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
