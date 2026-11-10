"""Swap one native text effect while preserving its frozen spoken anchors."""

from pathlib import Path

from .errors import ApiError
from .motion_library import read_json
from .motion_parameter_contracts import input_contract
from .video_editing_contracts import (
    EditingEffectChoice,
    EditingEffectTarget,
    NativeEffectEdit,
    SemanticBeat,
    SemanticPlan,
    Transcript,
)
from .video_editing_episode_compiler import EpisodeRecipeBundle
from .video_editing_overlay_recipes import build_text_effect_replacement
from .video_editing_overlay_templates import overlay_template, validate_template_plan
from .video_editing_planner import validate_plan


def _text_groups(package: Path, template: dict) -> dict[str, dict]:
    allowed = {slot["group_id"] for slot in template["slots"]}
    return {
        row["id"]: row
        for row in read_json(package / "catalog/groups.json")["groups"]
        if row["id"] in allowed and row["kind"] == row["backend"] == "subtitle"
    }


def _editable(beat: SemanticBeat, bundle: EpisodeRecipeBundle, groups: dict) -> bool:
    entry = bundle.entries.get(beat.id)
    return bool(
        beat.group_id in groups
        and beat.native_text
        and not beat.asset_ids
        and not beat.native_media
        and entry
        and entry.carrier == "text"
        and entry.placement.layer == "subtitle"
        and bundle.sound
        and any(cue.beat_id == beat.id for cue in bundle.sound.fx)
    )


def _replace(
    package: Path,
    edits: list[NativeEffectEdit],
    semantic: SemanticPlan,
    bundle: EpisodeRecipeBundle,
    transcript: Transcript,
    template: dict,
    groups: dict[str, dict],
    choice_snapshot: dict | None,
    asset_ids: set[str],
) -> tuple[SemanticPlan, EpisodeRecipeBundle, list[dict]]:
    if bundle.sound is None:
        raise ValueError("An effect replacement needs a saved sound plan")
    avoided = {
        row["target_id"]
        for row in (choice_snapshot or {}).get("notes", [])
        if row["target_kind"] == "bundled_asset" and row["choice"] == "avoid"
    }
    selected = {edit.beat_id: edit.group_id for edit in edits}
    beats = []
    entries = bundle.entries.copy()
    cues = {}
    applied = []
    for beat in semantic.beats:
        target = selected.get(beat.id)
        if target is None:
            beats.append(beat)
            continue
        if (
            target == beat.group_id
            or target not in groups
            or not _editable(beat, bundle, groups)
        ):
            raise ValueError("Select a compatible text effect from the same template")
        changed = beat.model_copy(
            update={
                "group_id": target,
                "reason": "用户选择替换本段原生文字动效，沿用同一段实录词点。",
            }
        )
        try:
            entries[beat.id], cues[beat.id] = build_text_effect_replacement(
                package, groups[target], changed, transcript, template["id"], avoided
            )
        except (ApiError, KeyError) as error:
            raise ValueError(
                "The replacement cannot use these original word anchors"
            ) from error
        if entries[beat.id].recipe.get("dependency_ids"):
            raise ValueError("Replacement choices require their packaged fonts")
        beats.append(changed)
        applied.append(
            {
                "beat_id": beat.id,
                "original_group_id": beat.group_id,
                "applied_group_id": target,
                "first_token_id": beat.first_token_id,
                "last_token_id": beat.last_token_id,
                "locked_by_user": True,
            }
        )
    if len(applied) != len(edits):
        raise ValueError("Unknown or duplicated effect replacement segment")
    revised = semantic.model_copy(update={"beats": beats})
    validate_plan(revised, transcript, package, asset_ids, choice_snapshot)
    validate_template_plan(revised, template, complete=True)
    fx = []
    for cue in bundle.sound.fx:
        if cue.beat_id not in selected:
            fx.append(cue)
        elif cue.beat_id in cues:
            fx.append(cues.pop(cue.beat_id))
    sound = bundle.sound.model_copy(update={"fx": fx})
    return (
        revised,
        bundle.model_copy(update={"entries": entries, "sound": sound}),
        applied,
    )


def apply_effect_edits(
    package: Path,
    edits: list[NativeEffectEdit],
    semantic: SemanticPlan,
    bundle: EpisodeRecipeBundle,
    transcript: Transcript,
    choice_snapshot: dict | None,
    asset_ids: set[str],
) -> tuple[SemanticPlan, EpisodeRecipeBundle, list[dict]]:
    if not bundle.overlay_template_id:
        raise ValueError("Effect replacement requires the saved combination template")
    template = overlay_template(bundle.overlay_template_id)
    return _replace(
        package,
        edits,
        semantic,
        bundle,
        transcript,
        template,
        _text_groups(package, template),
        choice_snapshot,
        asset_ids,
    )


def effect_edit_targets(
    package: Path,
    semantic: SemanticPlan,
    bundle: EpisodeRecipeBundle,
    transcript: Transcript,
    choice_snapshot: dict | None,
    asset_ids: set[str],
) -> list[EditingEffectTarget]:
    if not bundle.overlay_template_id:
        return []
    try:
        template = overlay_template(bundle.overlay_template_id)
    except ValueError:
        return []
    groups = _text_groups(package, template)
    compatible: dict[tuple[frozenset[str], frozenset[str]], list[str]] = {}
    for gid, group in groups.items():
        contract = input_contract(package, group)
        key = (
            frozenset(contract["text_paths"]),
            frozenset(event["path"] for event in contract["event_paths"]),
        )
        compatible.setdefault(key, []).append(gid)
    result = []
    for beat in semantic.beats:
        if not _editable(beat, bundle, groups):
            continue
        choices = []
        paths = (
            frozenset(anchor.path for anchor in beat.native_text),
            frozenset(anchor.path for anchor in beat.native_events),
        )
        for gid in compatible.get(paths, []):
            if gid == beat.group_id:
                continue
            try:
                _replace(
                    package,
                    [NativeEffectEdit(beat_id=beat.id, group_id=gid)],
                    semantic,
                    bundle,
                    transcript,
                    template,
                    groups,
                    choice_snapshot,
                    asset_ids,
                )
            except ValueError:
                continue
            choices.append(EditingEffectChoice(group_id=gid, name=groups[gid]["name"]))
        if choices:
            result.append(EditingEffectTarget(beat_id=beat.id, choices=choices))
    return result
