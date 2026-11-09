"""Compile measured semantic beats into the unmodified original episode protocol.

The model supplies word IDs and meaning. Trusted current-episode recipes supply
native design/placement. Missing recipes never become a silent Z-M00 fallback.
"""

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaViolation
from pydantic import Field, model_validator

from .config import Settings
from .motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from .video_editing_browser_clocks import CARD_GROUP
from .video_editing_captioning import write_caption_receipt
from .video_editing_contracts import NativeRenderEdits, SemanticPlan, Transcript
from .video_editing_hypit import hypit_tools, internal_hypit_available, requires_hypit
from .video_editing_hypit_strips import (
    STAGGER_GROUPS,
    STRIP_SIDECAR,
    stagger_audio_frame,
    stagger_events,
)
from .video_editing_native_compiler import compile_native_job
from .video_editing_native_layout import BACKDROP_GROUP
from .video_editing_native_sound import NativeSoundDesign, compile_sound
from .video_editing_overlay_templates import (
    MIN_OVERLAY_TYPES,
    PICTURE_TEMPLATE_ID,
    overlay_template,
    validate_template_plan,
)
from .video_editing_pipeline import EditingFailure, baseline_documents, layout_captions
from .video_editing_planner import validate_plan
from .video_editing_render_edits import (
    FULL_FRAME,
    NATIVE_PORTRAIT_INSETS,
    continuous_overlay_groups,
    edited_segment_receipt,
    source_only,
    validate_render_edits,
)
from .video_studio_schemas import StrictVideoModel


class NativePlacement(StrictVideoModel):
    layer: Literal["scene", "overlay", "subtitle"]
    rect: list[float] = Field(min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        x, y, width, height = self.rect
        if (
            not all(math.isfinite(v) for v in self.rect)
            or min(x, y) < 0
            or min(width, height) <= 0
            or x + width > 1
            or y + height > 1
        ):
            raise ValueError("Native placement leaves the current output frame")
        return self


class NativeEpisodeEntry(StrictVideoModel):
    recipe: dict[str, Any]
    placement: NativePlacement
    carrier: Literal["text", "picture"]


class EpisodeRecipeBundle(StrictVideoModel):
    version: Literal["tengli.episode-recipes/1"]
    library_release: str
    source_sha256: str
    transcript_sha256: str
    planning_origin: Literal["operator_candidate", "tengli_gateway"]
    source_review: str = Field(min_length=1, max_length=2000)
    design: dict[str, Any]
    typography: dict[str, Any] | None
    layout_policy: dict[str, Any]
    protected_regions: list[dict[str, Any]] = Field(default_factory=list)
    entries: dict[str, NativeEpisodeEntry]
    overlay_template_id: str | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    intentional_backdrop_beat_ids: list[str] = Field(
        default_factory=list, max_length=60, exclude_if=lambda value: not value
    )
    tools: dict[str, str] = Field(default_factory=dict)
    sound_mode: Literal["original_voice_only", "native_mix"]
    sound: NativeSoundDesign | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def sound_mode_matches_design(self) -> Self:
        if (self.sound_mode == "native_mix") != (self.sound is not None):
            raise ValueError("Native mix requires a current sound design")
        if self.typography is None and not self.overlay_template_id:
            raise ValueError(
                "Source-sized typography is only available to overlay templates"
            )
        return self


RELATION_MAPPING = {
    "parallel",
    "contrast",
    "cause",
    "sequence",
    "condition",
    "transformation",
}


def compile_episode(
    root: Path,
    prepared: dict,
    transcript: Transcript,
    semantic: SemanticPlan,
    authoring: EpisodeRecipeBundle,
    asset_files: dict[str, dict[str, Any]],
    options: dict,
    settings: Settings,
    choice_snapshot: dict[str, Any] | None = None,
    verified_gateway_plan_hash: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Prepare original episode/selection/bindings, without claiming a render."""
    root = root.resolve()
    package = settings.video_editing_library_dir
    semantic_hash = hashlib.sha256(semantic.model_dump_json().encode()).hexdigest()
    if (
        authoring.planning_origin == "tengli_gateway"
        and verified_gateway_plan_hash != semantic_hash
    ):
        raise EditingFailure("EDITING_PLANNER_PROVENANCE_REQUIRED")
    if options.get("source_subtitles") not in {"none", "present"}:
        raise EditingFailure("EDITING_SOURCE_SUBTITLES_REVIEW_REQUIRED")
    if root.is_relative_to(package.resolve()) or (root / "episode.json").exists():
        raise ValueError("Use a fresh instance outside the original library")
    # Reject non-finite trusted recipe numbers too; no model code or DSL is evaluated.
    json.dumps(authoring.model_dump(mode="json"), allow_nan=False)
    file = root / "transcript.json"
    if (
        authoring.library_release != MOTION_SHA256
        or authoring.source_sha256 != prepared["source_sha256"]
        or transcript.source_sha256 != prepared["source_sha256"]
        or transcript.audio_sha256 != prepared["audio_sha256"]
        or transcript.duration_ms != prepared["duration_ms"]
        or not file.is_file()
        or sha256(file) != authoring.transcript_sha256
        or Transcript.model_validate(read_json(file)) != transcript
    ):
        raise EditingFailure("EDITING_PLAN_SOURCE_CHANGED")
    validate_plan(semantic, transcript, package, set(asset_files), choice_snapshot)
    edits = None
    if options.get("native_edits") is not None:
        try:
            edits = NativeRenderEdits.model_validate(options["native_edits"])
            validate_render_edits(
                edits,
                semantic.model_dump(mode="json"),
                authoring.model_dump(mode="json"),
                choice_snapshot,
            )
        except ValueError as error:
            raise EditingFailure("EDITING_NATIVE_EDITS_INVALID") from error
    groups = {g["id"]: g for g in read_json(package / "catalog/groups.json")["groups"]}
    relation_types = set(
        read_json(package / "params.schema.json")["properties"]["production"][
            "properties"
        ]["beats"]["items"]["properties"]["relation"]["properties"]["type"]["enum"]
    )
    if len(groups) != 132:
        raise EditingFailure("EDITING_LIBRARY_INCOMPLETE")
    continuous_base = (
        options.get("delivery") == "preview_first"
        or authoring.overlay_template_id is not None
    )
    if authoring.overlay_template_id:
        validate_template_plan(
            semantic, overlay_template(authoring.overlay_template_id), complete=True
        )
    if (
        continuous_base
        and len(
            continuous_overlay_groups(
                semantic.model_dump(mode="json"),
                authoring.model_dump(mode="json"),
                {
                    gid
                    for gid, group in groups.items()
                    if group.get("kind") == "subtitle"
                    and group.get("backend") == "subtitle"
                },
                set(edits.source_only_beat_ids) if edits else None,
                allow_hypit_insets=options["source_subtitles"] == "none"
                and internal_hypit_available(settings, workspace_id),
                allow_question_insets=options["source_subtitles"] == "none",
                scene_groups={
                    gid
                    for gid, group in groups.items()
                    if group.get("kind") == "visual"
                }
                if options["source_subtitles"] == "none"
                else None,
            )
        )
        < MIN_OVERLAY_TYPES
    ):
        raise EditingFailure("EDITING_CONTINUOUS_COMBINATION_REQUIRED")
    capabilities = {
        c["group_id"]: c
        for c in read_json(package / "catalog/relationship-capabilities.json")["groups"]
    }
    expected = {b.id for b in semantic.beats if b.group_id != "Z-M00"}
    if set(authoring.entries) - expected:
        raise EditingFailure("EDITING_UNUSED_NATIVE_RECIPE")
    backdrop_beats = set(authoring.intentional_backdrop_beat_ids)
    if backdrop_beats and (
        not continuous_base
        or not backdrop_beats
        <= {b.id for b in semantic.beats if b.group_id == BACKDROP_GROUP}
    ):
        raise EditingFailure("EDITING_NATIVE_BACKDROP_INTENT_INVALID")
    backdrop_shots = []
    episode, selection, captions = baseline_documents(
        root, prepared, transcript, options, settings
    )
    source_shot = copy.deepcopy(episode["shots"][0])
    episode["shots"] = []
    selection["decisions"] = []
    bindings: dict[str, dict[str, str]] = {
        "resources": {},
        "tools": dict(authoring.tools),
    }
    if set(authoring.tools) - {
        "chrome",
        "node",
        "hypit",
        "ffmpeg",
        "ffprobe",
        "python",
    }:
        raise EditingFailure("EDITING_NATIVE_TOOL_NOT_ALLOWED")
    for value in authoring.tools.values():
        if not Path(value).is_file():
            raise EditingFailure("EDITING_NATIVE_TOOL_MISSING")
    if requires_hypit(semantic.model_dump(mode="json")):
        try:
            bindings["tools"].update(hypit_tools(settings, workspace_id))
        except (ValueError, OSError) as error:
            raise EditingFailure("EDITING_HYPIT_INTERNAL_ONLY") from error
    episode.update(
        design=copy.deepcopy(authoring.design),
        layout_policy=copy.deepcopy(authoring.layout_policy),
        protected_regions=copy.deepcopy(authoring.protected_regions),
    )
    if authoring.typography is not None:
        episode["typography"] = copy.deepcopy(authoring.typography)
    if episode["design"].get("caption_font_id") != options["caption_font_id"]:
        raise EditingFailure("EDITING_CAPTION_DESIGN_MISMATCH")
    episode["editorial"].update(
        {
            "source_verified": True,
            "source_review": authoring.source_review,
            "audience_question": semantic.audience_question,
            "argument_outline": semantic.argument_outline,
            "style_reason": semantic.style_reason,
            "planning_origin": authoring.planning_origin,
            "semantic_review": "unreviewed",
        }
    )
    layout_captions(episode, captions, settings)
    episode["production"].update(beats=[], materials=[])
    tokens = transcript.tokens
    positions = {t.id: i for i, t in enumerate(tokens)}
    issues: list[dict[str, Any]] = []
    compiled: list[dict[str, Any]] = []
    sound_events: dict[tuple[str, str], tuple[int, dict]] = {}
    excluded_beats = set(edits.source_only_beat_ids) if edits else set()
    applied_edits = []
    prior_end = 0
    for index, beat in enumerate(semantic.beats):
        first, last = positions[beat.first_token_id], positions[beat.last_token_id]
        start_ms, end_ms = tokens[first].start_ms, tokens[last].end_ms
        if start_ms < prior_end or end_ms <= start_ms:
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "WORD_CLOCK_OVERLAP",
                }
            )
            continue
        prior_end = end_ms
        start, end = start_ms / 1000, end_ms / 1000
        item_text = "".join(t.text for t in tokens[first : last + 1])
        shot_indices = []
        entry = authoring.entries.get(beat.id)
        if beat.id in excluded_beats:
            applied_edits.append(edited_segment_receipt(beat, start_ms, end_ms))
            beat = source_only(beat)
            entry = None
        if beat.group_id != "Z-M00" and entry is None:
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "NATIVE_RECIPE_REQUIRED",
                }
            )
            continue
        if (
            beat.group_id != "Z-M00"
            and beat.relation in RELATION_MAPPING
            and not beat.relation_items
        ):
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "RELATION_MAPPING_REQUIRED",
                }
            )
            continue
        if (
            entry
            and groups[beat.group_id]["kind"] == "subtitle"
            and entry.placement.layer != "subtitle"
        ):
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "SUBTITLE_LAYER_REQUIRED",
                }
            )
            continue
        if (
            entry
            and entry.carrier == "picture"
            and (
                not beat.relation_items
                or any(
                    not i.asset_ids or not i.native_media_paths
                    for i in beat.relation_items
                )
            )
        ):
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "PICTURE_RELATION_ASSETS_REQUIRED",
                }
            )
            continue
        capability = capabilities.get(beat.group_id)
        if (
            entry
            and beat.relation_items
            and capability
            and (
                entry.carrier not in capability["carriers"]
                or not capability["min_items"]
                <= len(beat.relation_items)
                <= capability["max_items"]
            )
        ):
            issues.append(
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "code": "NATIVE_RELATION_CAPACITY_REQUIRED",
                }
            )
            continue
        if beat.group_id == "Z-M00" and not continuous_base:
            # Native source pages only; speech stays on the single original audio.
            for page in range(math.ceil((end - start) / 15)):
                a, b = start + page * 15, min(end, start + (page + 1) * 15)
                shot = copy.deepcopy(source_shot)
                shot.update(start_seconds=a, end_seconds=b)
                shot["config"]["timing"]["duration_seconds"] = b - a
                shot["config"]["media"]["presenter"].update(
                    offset_seconds=a, duration_seconds=b - a
                )
                shot["intent"] = {
                    "expected_understanding": item_text,
                    "reason": beat.reason,
                }
                shot_indices.append(len(episode["shots"]))
                episode["shots"].append(shot)
        elif beat.group_id != "Z-M00":
            assert entry is not None
            directory = root / "compiled-native" / f"{index:03}-{beat.group_id}"
            try:
                job = compile_native_job(
                    package,
                    directory,
                    beat,
                    transcript,
                    entry.recipe,
                    asset_files,
                    native_bindings_file=settings.video_editing_native_bindings_file,
                )
                part_bindings = read_json(directory / "bindings.json")
                hypit_entries = {}
                if beat.group_id in STAGGER_GROUPS:
                    stem = f"{len(episode['shots']):03}-{beat.group_id}"
                    part = directory / STRIP_SIDECAR
                    if (
                        sha256(part)
                        != part_bindings["tengli_hypit_strips"]["component"]
                    ):
                        raise ValueError(
                            "Hypit strip receipt changed during compilation"
                        )
                    sidecar = root / "hypit-strips" / f"{stem}.json"
                    strip = read_json(part)
                    atomic_json(sidecar, strip)
                    digest = sha256(sidecar)
                    bindings.setdefault("tengli_hypit_strips", {})[stem] = digest
                    hypit_entries = {
                        path: {
                            "group_id": beat.group_id,
                            "shot": stem,
                            "sidecar_sha256": digest,
                            "index": i,
                            "frame": frame,
                            "audible_frame": stagger_audio_frame(beat.group_id, frame),
                        }
                        for i, (path, frame) in enumerate(
                            zip(
                                stagger_events(beat.group_id),
                                strip["entry_frames"],
                                strict=True,
                            )
                        )
                    }
                for rid, value in part_bindings["resources"].items():
                    if (
                        rid in bindings["resources"]
                        and bindings["resources"][rid] != value
                    ):
                        raise ValueError("Conflicting instance resource binding")
                    bindings["resources"][rid] = value
                if authoring.sound:
                    for event in read_json(directory / "word-bindings.json")["events"]:
                        if event["path"] in hypit_entries:
                            event["hypit_entry"] = hypit_entries[event["path"]]
                        sound_events[beat.id, event["path"]] = (
                            len(episode["shots"]),
                            event,
                        )
                shot_indices.append(len(episode["shots"]))
                if beat.id in backdrop_beats:
                    backdrop_shots.append(shot_indices[-1])
                episode["shots"].append(
                    {
                        "group_id": beat.group_id,
                        "config": job["config"],
                        "start_seconds": start,
                        "end_seconds": end,
                        "layer": entry.placement.layer,
                        "rect": entry.placement.rect,
                        "intent": {
                            "expected_understanding": item_text,
                            "reason": beat.reason,
                        },
                    }
                )
                compiled.append(
                    {
                        "beat_id": beat.id,
                        "group_id": beat.group_id,
                        "job_sha256": sha256(directory / "job.json"),
                        "compile_receipt_sha256": sha256(
                            directory / "compile-receipt.json"
                        ),
                        "placement_reason": entry.placement.reason,
                    }
                )
            except (
                ValueError,
                KeyError,
                IndexError,
                FileNotFoundError,
                SchemaViolation,
            ) as error:
                issues.append(
                    {
                        "beat_id": beat.id,
                        "group_id": beat.group_id,
                        "code": "NATIVE_INPUT_CONTRACT_REQUIRED",
                        "exception_type": type(error).__name__,
                    }
                )
                continue
        for shot_index in shot_indices:
            selection["decisions"].append(
                {
                    "shot_index": shot_index,
                    "selected_group_id": beat.group_id,
                    "viewer_task": item_text,
                    "reason": beat.reason,
                    "considered": [{"group_id": beat.group_id}],
                }
            )
        production_beat: dict[str, Any] = {
            "id": beat.id,
            "importance": "key" if beat.emphasis_token_ids else "support",
            "semantic_relation": beat.relation,
            "spoken_text": item_text,
            "visual_expression": beat.group_id if beat.group_id != "Z-M00" else None,
            "intentional_rest_reason": beat.reason
            if beat.group_id == "Z-M00"
            else None,
        }
        if beat.relation_items:
            items = [
                {
                    "id": i.id,
                    "meaning": "".join(
                        t.text
                        for t in tokens[
                            positions[i.first_token_id] : positions[i.last_token_id] + 1
                        ]
                    ),
                    "material_ids": i.asset_ids,
                }
                for i in beat.relation_items
            ]
            mapped_relation = {
                "type": beat.relation,
                "count": len(items),
                "items": items,
                "expressions": [
                    {
                        "carrier": entry.carrier if entry else "text",
                        "item_ids": [i["id"] for i in items],
                        "shot_indices": shot_indices,
                        "reason": beat.reason,
                    }
                ]
                if entry
                else [],
                **({"intentional_rest_reason": beat.reason} if not entry else {}),
            }
            if beat.relation in relation_types:
                production_beat["relation"] = mapped_relation
            else:
                production_beat["adapter_relation"] = mapped_relation
                production_beat["native_relation_scope"] = (
                    "not_in_original_relation_schema"
                )
        episode["production"]["beats"].append(production_beat)
    if authoring.overlay_template_id == PICTURE_TEMPLATE_ID:
        card_windows = [
            (shot["start_seconds"], shot["end_seconds"])
            for shot in episode["shots"]
            if shot["group_id"] == CARD_GROUP
        ]
        if card_windows:
            caption_role = episode["typography"]["caption"]
            overrides = caption_role.setdefault("layout_overrides", [])
            overrides.extend(
                {
                    "start_seconds": caption["start_seconds"],
                    "end_seconds": caption["end_seconds"],
                    "baseline_y_px": round(episode["output"]["height"] * 732 / 1280),
                    "reason": "将主字幕放在原生三张图卡的上方。",
                }
                for caption in episode["captions"]
                if any(
                    caption["start_seconds"] < end and start < caption["end_seconds"]
                    for start, end in card_windows
                )
            )
    for aid, asset in asset_files.items():
        if not any(
            aid in b.asset_ids for b in semantic.beats if b.id not in excluded_beats
        ):
            continue
        path = Path(asset["path"]).resolve()
        if not path.is_file() or sha256(path) != asset["sha256"]:
            issues.append({"asset_id": aid, "code": "CURRENT_MATERIAL_CHANGED"})
            continue
        episode["production"]["materials"].append(
            {
                "id": aid,
                "path": str(path),
                "sha256": asset["sha256"],
                "kind": asset.get("kind", "original_material"),
                "semantic_use": asset.get("semantic_use", ""),
                "viewed_identity": asset.get("viewed_identity"),
                "source": asset.get("source"),
                "license": asset.get("license"),
            }
        )
    sound_plan = None
    if authoring.sound and not issues:
        try:
            sound_plan = compile_sound(
                package,
                transcript,
                episode,
                authoring.sound,
                sound_events,
                choice_snapshot,
                edits,
            )
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            issues.append({"code": "EDITING_SOUND_INPUTS_REQUIRED"})
    try:
        Draft202012Validator(read_json(package / "params.schema.json")).validate(
            episode
        )
    except SchemaViolation as error:
        issues.append(
            {
                "code": "ORIGINAL_EPISODE_SCHEMA_REJECTED",
                "field": ".".join(map(str, error.absolute_path)),
            }
        )
    diagnostic = {
        "version": "tengli.episode-compilation/1",
        "library_release": MOTION_SHA256,
        "catalog_groups_preserved": len(groups),
        "planning_origin": authoring.planning_origin,
        "source_sha256": prepared["source_sha256"],
        "transcript_sha256": sha256(file),
        "semantic_sha256": semantic_hash,
        "choice_snapshot_sha256": (choice_snapshot or {}).get("sha256"),
        "compiled_native_jobs": compiled,
        **(
            {
                "visual_base": "continuous_original_source",
                "narration_policy": "continuous_original_audio",
                "full_scene_group_ids": sorted(
                    {
                        shot["group_id"]
                        for shot in episode["shots"]
                        if shot["layer"] == "scene"
                    }
                ),
                "overlay_group_ids": sorted({row["group_id"] for row in compiled}),
                "overlay_occurrences": len(compiled),
            }
            if continuous_base
            else {}
        ),
        **(
            {
                "native_edits": edits.model_dump(mode="json"),
                "applied_source_only_segments": applied_edits,
            }
            if edits
            else {}
        ),
        "episode_schema_validation": "passed" if not issues else "not_admitted",
        "issues": issues,
        "native_execution": "not_performed",
        "semantic_review": "unreviewed",
        "visual_review": "unreviewed",
        "hearing_review": "unreviewed",
    }
    atomic_json(root / "compile-diagnostics.json", diagnostic)
    if issues:
        if any(row["code"] == "EDITING_SOUND_INPUTS_REQUIRED" for row in issues):
            raise EditingFailure("EDITING_SOUND_INPUTS_REQUIRED")
        raise EditingFailure("EDITING_NATIVE_INPUTS_REQUIRED")
    if sound_plan is not None:
        atomic_json(root / "audio-plan.json", sound_plan)
    atomic_json(root / "semantic-plan.json", semantic.model_dump(mode="json"))
    atomic_json(root / "episode-recipes.json", authoring.model_dump(mode="json"))
    atomic_json(root / "caption-anchors.json", captions)
    atomic_json(
        root / "caption-adapter-layout.json",
        episode["editorial"]["caption_line_layout"],
    )
    write_caption_receipt(
        root, transcript, captions, options["source_subtitles"] == "none"
    )
    atomic_json(root / "bindings.json", bindings)
    atomic_json(root / "selection.json", selection)
    if backdrop_shots:
        atomic_json(
            root / "layout-intent.json", {"sg_s10_backdrop_shots": backdrop_shots}
        )
    if continuous_base:
        inset_shots = [
            i
            for i, shot in enumerate(episode["shots"])
            if shot["group_id"] in NATIVE_PORTRAIT_INSETS and shot["rect"] != FULL_FRAME
        ]
        if inset_shots:
            atomic_json(root / "inset-layout-intent.json", {"shots": inset_shots})
    atomic_json(root / "episode.json", episode)
    return episode
