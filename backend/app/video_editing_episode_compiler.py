"""Compile measured semantic beats into the unmodified original episode protocol.

The model supplies word IDs and meaning. Trusted current-episode recipes supply
native design/placement. Missing recipes never become a silent Z-M00 fallback.
"""

import copy
import hashlib
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaViolation
from pydantic import Field, model_validator

from .config import Settings
from .motion_browser_originals import (
    BROWSER_ORIGINALS_KEY,
    BROWSER_ORIGINALS_REQUIRED,
    BrowserOriginalsMissing,
)
from .motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from .video_editing_azl_panels import (
    AZL_CAPTION_BASELINE,
    AZL_GROUPS,
    AZL_LAYOUT_INTENT,
    azl_backing,
    require_azl_compositor,
)
from .video_editing_bg03_readability import BG_OFFSET_GROUP, apply_outline
from .video_editing_browser_boot import (
    BROWSER_BOOT_FONTS_REQUIRED,
    BrowserBootFontsMissing,
)
from .video_editing_browser_clocks import (
    CARD_GROUP,
    NUMBERED_GROUP,
    SPLIT_HORIZONTAL,
    SPLIT_HORIZONTAL_CAPTION_BASELINE,
)
from .video_editing_browser_rotation import ROTATION_GROUP
from .video_editing_captioning import write_caption_receipt
from .video_editing_collage_scene import COLLAGE_GROUP, COLLAGE_TEMPLATE_ID
from .video_editing_contracts import NativeRenderEdits, SemanticPlan, Transcript
from .video_editing_cut_scenes import CUT_TEMPLATE_ID
from .video_editing_cxbr import CXBR_CAPTION_INTENT, CXBR_PURPOSES, CXBR_TEMPLATE_ID
from .video_editing_first_groups import PRODUCT_GROUP_ID
from .video_editing_handoff_scenes import HANDOFF_TEMPLATE_ID
from .video_editing_highlights import apply_highlight_edits
from .video_editing_hypit import (
    PICTURE_CAPTION_BASELINE,
    PICTURE_GROUP,
    HypitToolchainError,
    hypit_tools,
    requires_hypit,
)
from .video_editing_hypit_chart import FLOW_CHART_CAPTION_BASELINE
from .video_editing_hypit_strips import (
    FLOW_GROUP,
    LIVE_STRIP_GROUP,
    PRESENTER_LABEL_GROUP,
    PRICE_CARD_GROUP,
    SLANT_CAPTION_BASELINE,
    SLANT_GROUP,
    STAGGER_GROUPS,
    STRIP_SIDECAR,
    stagger_audio_frame,
    stagger_events,
)
from .video_editing_image_edits import apply_image_edits
from .video_editing_judgment import JUDGMENT_GROUP
from .video_editing_line_branch import LINE_GROUP
from .video_editing_native_compiler import compile_native_job
from .video_editing_native_content import PACKAGE_GROUP, ROLE_CHAIN_GROUP
from .video_editing_native_layout import (
    BACKDROP_GROUP,
    LAYERED_SUBTITLE_ROLE_GROUPS,
    TEXT_HANDOFF_GROUP,
    projected_scene_end,
)
from .video_editing_native_sound import NativeSoundDesign, compile_sound
from .video_editing_overlay_templates import (
    AZL_TEMPLATE_ID,
    JUDGMENT_TEMPLATE_ID,
    LAYERED_SUBTITLE_TEMPLATES,
    LEGACY_PICTURE_TEMPLATE_ID,
    LINE_TEMPLATE_ID,
    LIVE_STRIP_TEMPLATE_ID,
    MIN_OVERLAY_TYPES,
    NUMBERED_TEMPLATE_ID,
    PACKAGE_TEMPLATE_ID,
    PICTURE_TEMPLATE_ID,
    PRESENTER_LABEL_TEMPLATE_ID,
    PRESENTER_MOTION_TEMPLATE_ID,
    PRESENTER_TEMPLATE_ID,
    ROTATION_TEMPLATE_ID,
    SYNC_SUBTITLE_TEMPLATES,
    TEXT_HANDOFF_TEMPLATES,
    YY_OPENING_TEMPLATES,
    overlay_template,
    validate_template_plan,
)
from .video_editing_pipeline import (
    EditingFailure,
    baseline_documents,
    layout_captions,
    run,
)
from .video_editing_planner import validate_plan
from .video_editing_presenter_motion import PRESENTER_MOTION_GROUPS
from .video_editing_question_card import question_card_a_shot
from .video_editing_render_edits import (
    FULL_FRAME,
    NATIVE_PORTRAIT_INSETS,
    continuous_overlay_groups,
    edited_segment_receipt,
    source_only,
    validate_render_edits,
)
from .video_editing_role_scene import ROLE_TEMPLATE_ID
from .video_editing_story_panels import PANEL_TEMPLATE_ID, TRIPTYCH, triptych_entrance
from .video_editing_unified_scenes import (
    BROWSER_LIST_SCENES,
    TRANSLATION_GROUP,
    UNIFIED_CAPTION_INTENT,
    UNIFIED_SCENE_GROUPS,
    UNIFIED_TEMPLATES,
    UNIFIED_TRANSLATION_CAPTION_BASELINE,
    UNIFIED_WINDOW_CAPTION_BASELINE,
    UNIFIED_WINDOW_GROUP,
    split_unified_caption_lanes,
)
from .video_editing_yy6_scenes import YY6_GROUPS
from .video_editing_yy_openings import (
    YY_OPENING_ALL_GROUPS,
    YY_OPENING_CAPTION_BASELINE,
    YY_OPENING_CAPTION_INTENT,
    YY_OPENING_LOWER_CAPTION_BASELINE,
    YY_OPENING_LOWER_TEXT_BANDS,
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
    *,
    guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Prepare original episode/selection/bindings, without claiming a render."""
    root = root.resolve()
    package = settings.video_editing_library_dir
    original_semantic = semantic
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
    highlights: list[dict[str, Any]] = []
    if edits and edits.highlight_edits:
        try:
            semantic, highlights = apply_highlight_edits(
                edits.highlight_edits,
                semantic,
                authoring.model_dump(mode="json"),
                transcript,
            )
            validate_plan(
                semantic, transcript, package, set(asset_files), choice_snapshot
            )
        except ValueError as error:
            raise EditingFailure("EDITING_HIGHLIGHT_INVALID") from error
    image_replacements: list[dict[str, Any]] = []
    if edits and edits.image_edits:
        try:
            semantic, image_replacements = apply_image_edits(
                edits.image_edits,
                semantic,
                authoring.model_dump(mode="json"),
                asset_files,
                transcript,
            )
            validate_plan(
                semantic, transcript, package, set(asset_files), choice_snapshot
            )
        except (ValueError, KeyError) as error:
            raise EditingFailure("EDITING_IMAGE_EDIT_INVALID") from error
    effect_replacements: list[dict[str, Any]] = []
    if edits and edits.effect_edits:
        from .video_editing_effect_edits import apply_effect_edits

        try:
            semantic, authoring, effect_replacements = apply_effect_edits(
                package,
                edits.effect_edits,
                semantic,
                authoring,
                transcript,
                choice_snapshot,
                set(asset_files),
            )
        except ValueError as error:
            raise EditingFailure("EDITING_EFFECT_EDIT_INVALID") from error
    replaced_beats = {row["beat_id"]: row for row in effect_replacements}
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
    excluded_beats = set(edits.source_only_beat_ids) if edits else set()
    semantic_data = semantic.model_dump(mode="json")
    hypit_bindings = {}
    if requires_hypit(semantic_data, excluded_beats):
        try:
            hypit_bindings = hypit_tools(settings, workspace_id)
        except HypitToolchainError as error:
            raise EditingFailure(error.code) from error
    if (
        continuous_base
        and len(
            continuous_overlay_groups(
                semantic_data,
                authoring.model_dump(mode="json"),
                {
                    gid
                    for gid, group in groups.items()
                    if group.get("kind") == "subtitle"
                    and group.get("backend") == "subtitle"
                },
                excluded_beats,
                allow_hypit_insets=options["source_subtitles"] == "none"
                and bool(hypit_bindings),
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
    bindings["tools"].update(hypit_bindings)
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
                readability = None
                use_outline = (
                    authoring.overlay_template_id in SYNC_SUBTITLE_TEMPLATES
                    and beat.group_id == BG_OFFSET_GROUP
                )
                recipe = entry.recipe
                if use_outline:
                    recipe = copy.deepcopy(recipe)
                    apply_outline(recipe["config"], "both")
                    probe_dir = root / "readability-probes" / directory.name
                    compile_native_job(
                        package,
                        probe_dir,
                        beat,
                        transcript,
                        recipe,
                        asset_files,
                        native_bindings_file=settings.video_editing_native_bindings_file,
                    )
                    run(
                        [
                            settings.video_editing_python or sys.executable,
                            "-B",
                            "-X",
                            "utf8",
                            "-m",
                            "app.video_editing_bg03_readability",
                            "--package",
                            str(package.resolve()),
                            "--job",
                            str(probe_dir / "job.json"),
                        ],
                        root,
                        settings,
                        guard or (lambda: None),
                        "bg03_readability",
                    )
                    readability = read_json(probe_dir / "readability.json")
                    profile = readability["selected"]
                    if profile is None:
                        raise ValueError(
                            "BG-S03 subtitle roles collide without outlines"
                        )
                    apply_outline(recipe["config"], profile)
                    recipe["parameter_decisions"]["fonts"] = {
                        "both": "保持原字色、字号及原生双行细描边。",
                        "body": "保持原字色和字号，仅对白字加原生细描边。",
                        "clear": "保持原字色和字号，沿用无描边排版。",
                    }[profile]
                job = compile_native_job(
                    package,
                    directory,
                    beat,
                    transcript,
                    recipe,
                    asset_files,
                    native_bindings_file=settings.video_editing_native_bindings_file,
                    browser_originals_directory=root / "browser-originals",
                )
                part_bindings = read_json(directory / "bindings.json")
                hypit_entries = {}
                stagger_frames = None
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
                    stagger_frames = strip["frames"]
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
                if originals := part_bindings.get(BROWSER_ORIGINALS_KEY):
                    frozen = bindings.setdefault(BROWSER_ORIGINALS_KEY, {})
                    if any(
                        name in frozen and frozen[name] != row
                        for name, row in originals.items()
                    ):
                        raise ValueError("Conflicting frozen original browser image")
                    frozen.update(originals)
                if authoring.sound:
                    events = read_json(directory / "word-bindings.json")["events"]
                    if (
                        authoring.overlay_template_id == PANEL_TEMPLATE_ID
                        and beat.group_id == TRIPTYCH
                    ):
                        events.append(
                            triptych_entrance(beat, round(start * 1000), job["config"])
                        )
                    for event in events:
                        if event["path"] in hypit_entries:
                            event["hypit_entry"] = hypit_entries[event["path"]]
                        sound_events[beat.id, event["path"]] = (
                            len(episode["shots"]),
                            event,
                        )
                shot_indices.append(len(episode["shots"]))
                if beat.id in replaced_beats:
                    replaced_beats[beat.id]["shot_index"] = shot_indices[-1]
                if beat.id in backdrop_beats:
                    backdrop_shots.append(shot_indices[-1])
                picture_end = end
                if (
                    authoring.overlay_template_id in UNIFIED_TEMPLATES
                    and beat.group_id in UNIFIED_SCENE_GROUPS
                ):
                    fps = episode["output"]["fps"]
                    config = job["config"]
                    if beat.group_id in {SLANT_GROUP, PRICE_CARD_GROUP, FLOW_GROUP}:
                        assert stagger_frames is not None
                        frames = stagger_frames
                    elif beat.group_id == PICTURE_GROUP:
                        frames = config["frames"]
                    elif beat.group_id in BROWSER_LIST_SCENES:
                        frames = round(config["duration"] * fps)
                    else:
                        frames = round(config["timing"]["duration_seconds"] * fps)
                    picture_end = projected_scene_end(
                        start,
                        end,
                        frames,
                        fps,
                    )
                episode["shots"].append(
                    {
                        "group_id": beat.group_id,
                        "config": job["config"],
                        "start_seconds": start,
                        "end_seconds": (
                            projected_scene_end(
                                start,
                                end,
                                job["config"]["frames"],
                                episode["output"]["fps"],
                            )
                            if (
                                authoring.overlay_template_id == AZL_TEMPLATE_ID
                                and beat.group_id in AZL_GROUPS
                            )
                            or (
                                authoring.overlay_template_id == CXBR_TEMPLATE_ID
                                and beat.group_id in CXBR_PURPOSES
                            )
                            or (
                                authoring.overlay_template_id in YY_OPENING_TEMPLATES
                                and beat.group_id in YY6_GROUPS
                            )
                            else picture_end
                        ),
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
                        "shot_index": shot_indices[-1],
                        "job_sha256": sha256(directory / "job.json"),
                        "compile_receipt_sha256": sha256(
                            directory / "compile-receipt.json"
                        ),
                        "placement_reason": entry.placement.reason,
                        **({"readability": readability} if readability else {}),
                    }
                )
            except BrowserOriginalsMissing as error:
                issues.append(
                    {
                        "beat_id": beat.id,
                        "group_id": beat.group_id,
                        "code": BROWSER_ORIGINALS_REQUIRED,
                        "missing_original_images": error.missing,
                    }
                )
                continue
            except BrowserBootFontsMissing as error:
                issues.append(
                    {
                        "beat_id": beat.id,
                        "group_id": beat.group_id,
                        "code": BROWSER_BOOT_FONTS_REQUIRED,
                        "original_font_states": error.states,
                    }
                )
                continue
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
    caption_lane = {
        LINE_TEMPLATE_ID: (
            (LINE_GROUP, PACKAGE_GROUP),
            1208,
            "将主字幕放在线描或纸面场景的底部。",
        ),
        PACKAGE_TEMPLATE_ID: (
            (PACKAGE_GROUP,),
            1208,
            "将主字幕放在纸面规格场景的底部。",
        ),
        JUDGMENT_TEMPLATE_ID: (
            (JUDGMENT_GROUP,),
            1244,
            "将主字幕放在原判断画布的底部通道。",
        ),
        LEGACY_PICTURE_TEMPLATE_ID: (
            (CARD_GROUP,),
            732,
            "将主字幕放在原生三张图卡的上方。",
        ),
        PICTURE_TEMPLATE_ID: ((CARD_GROUP,), 732, "将主字幕放在原生三张图卡的上方。"),
        NUMBERED_TEMPLATE_ID: (
            (NUMBERED_GROUP,),
            1240,
            "将主字幕放在原生编号标签的下方。",
        ),
        LIVE_STRIP_TEMPLATE_ID: (
            (LIVE_STRIP_GROUP,),
            1240,
            "将主字幕放在原生斜切标签的下方。",
        ),
        PRESENTER_LABEL_TEMPLATE_ID: (
            (PRESENTER_LABEL_GROUP,),
            1240,
            "将主字幕放在原生人物标签的下方。",
        ),
        PRESENTER_TEMPLATE_ID: (
            ("LYO01", "LYO04"),
            1110,
            "将主字幕放在原生强调词的下方。",
        ),
        PRESENTER_MOTION_TEMPLATE_ID: (
            tuple(PRESENTER_MOTION_GROUPS),
            1230,
            "将主字幕移到同期人物运镜和分区构图的底部读区。",
        ),
        AZL_TEMPLATE_ID: (
            tuple(AZL_GROUPS),
            AZL_CAPTION_BASELINE,
            "主字幕进入原生板式下方的读区。",
        ),
        CXBR_TEMPLATE_ID: (
            tuple(CXBR_PURPOSES),
            1230,
            "主字幕放在原实景标题和纸条下方。",
        ),
        **dict.fromkeys(
            UNIFIED_TEMPLATES,
            (
                tuple(UNIFIED_SCENE_GROUPS),
                1257,
                "主字幕放在原生论点、人物窗与数量文字的下方。",
            ),
        ),
        **dict.fromkeys(
            YY_OPENING_TEMPLATES,
            (
                tuple(YY_OPENING_ALL_GROUPS),
                YY_OPENING_CAPTION_BASELINE,
                "月云川整帧开场在下方保留统一主字幕阅读区。",
            ),
        ),
        PRODUCT_GROUP_ID: (
            (*UNIFIED_SCENE_GROUPS, *PRESENTER_MOTION_GROUPS, *YY_OPENING_ALL_GROUPS),
            1230,
            "主字幕放在原生镜头的底部读区。",
        ),
        ROTATION_TEMPLATE_ID: (
            (ROTATION_GROUP,),
            1257,
            "将主字幕放在原生轮换图卡的下方。",
        ),
    }.get(authoring.overlay_template_id or "")
    if caption_lane:
        caption_groups, baseline, lane_reason = caption_lane
        unified = authoring.overlay_template_id in UNIFIED_TEMPLATES
        unified_baselines = {
            UNIFIED_WINDOW_GROUP: UNIFIED_WINDOW_CAPTION_BASELINE,
            TRANSLATION_GROUP: UNIFIED_TRANSLATION_CAPTION_BASELINE,
            COLLAGE_GROUP: UNIFIED_TRANSLATION_CAPTION_BASELINE,
            ROLE_CHAIN_GROUP: UNIFIED_TRANSLATION_CAPTION_BASELINE,
            FLOW_GROUP: FLOW_CHART_CAPTION_BASELINE,
        }
        effect_windows = [
            (
                shot["start_seconds"],
                shot["end_seconds"],
                YY_OPENING_LOWER_CAPTION_BASELINE
                if authoring.overlay_template_id in YY_OPENING_TEMPLATES
                and shot["group_id"] in YY_OPENING_LOWER_TEXT_BANDS
                else unified_baselines[shot["group_id"]]
                if unified and shot["group_id"] in unified_baselines
                else SPLIT_HORIZONTAL_CAPTION_BASELINE
                if shot["group_id"] == SPLIT_HORIZONTAL
                else SLANT_CAPTION_BASELINE
                if shot["group_id"] == SLANT_GROUP
                else PICTURE_CAPTION_BASELINE
                if shot["group_id"] == PICTURE_GROUP
                else baseline,
            )
            for shot in episode["shots"]
            if shot["group_id"] in caption_groups
        ]
        if effect_windows:
            if any(shot["group_id"] == FLOW_GROUP for shot in episode["shots"]):
                safe = episode["layout_policy"]["subtitle_safe_rect"]
                top = min(safe[1], 0.025)
                safe[3] += safe[1] - top
                safe[1] = top
            if unified:
                episode["captions"] = split_unified_caption_lanes(
                    episode["captions"], effect_windows
                )
            caption_role = episode["typography"]["caption"]
            overrides = caption_role.setdefault("layout_overrides", [])
            for caption in episode["captions"]:
                caption_baselines = [
                    y
                    for start, end, y in effect_windows
                    if caption["start_seconds"] < end and start < caption["end_seconds"]
                ]
                if not caption_baselines:
                    continue
                y = max(caption_baselines)
                overrides.append(
                    {
                        "start_seconds": caption["start_seconds"],
                        "end_seconds": caption["end_seconds"],
                        "baseline_y_px": round(episode["output"]["height"] * y / 1280),
                        "reason": "主字幕置于饼图和流式标签上方。"
                        if y == FLOW_CHART_CAPTION_BASELINE
                        else "主字幕进入人物窗下缘，避开原生标签和结论。"
                        if unified and y == UNIFIED_WINDOW_CAPTION_BASELINE
                        else "主字幕避开原生拼贴标签和短字幕。"
                        if authoring.overlay_template_id == COLLAGE_TEMPLATE_ID
                        and y == UNIFIED_TRANSLATION_CAPTION_BASELINE
                        else "主字幕位于插画内原生角色字和短字幕下方。"
                        if authoring.overlay_template_id == ROLE_TEMPLATE_ID
                        and y == UNIFIED_TRANSLATION_CAPTION_BASELINE
                        else "主字幕放在双语换字的原生释义下方。"
                        if unified and y == UNIFIED_TRANSLATION_CAPTION_BASELINE
                        else "主字幕放在原横向分屏前两排标签之间。"
                        if y == SPLIT_HORIZONTAL_CAPTION_BASELINE
                        else lane_reason,
                    }
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
                "viewed_identity": (
                    "本期实录讲述者与现场画面"
                    if authoring.overlay_template_id
                    in {
                        CUT_TEMPLATE_ID,
                        PANEL_TEMPLATE_ID,
                        HANDOFF_TEMPLATE_ID,
                        PRODUCT_GROUP_ID,
                    }
                    and asset.get("kind") == "original_video"
                    and asset["sha256"] == transcript.source_sha256
                    and not asset.get("viewed_identity")
                    else asset.get("viewed_identity")
                ),
                "source": asset.get("source"),
                "license": asset.get("license"),
            }
        )
    azl_shots = [
        index
        for index, shot in enumerate(episode["shots"])
        if authoring.overlay_template_id == AZL_TEMPLATE_ID
        and shot["group_id"] in AZL_GROUPS
    ]
    if azl_shots:
        try:
            require_azl_compositor(package)
            episode["visual_scenes"] = [
                azl_backing(episode["shots"][index], episode, index)
                for index in azl_shots
            ]
            selection["decisions"].extend(
                {
                    "scene_id": backing["id"],
                    "viewer_task": "保留原板式下方独立的主字幕读区。",
                    "reason": "整帧底色与板式同步切换，保留原构图比例。",
                    "considered": [{"group_id": episode["shots"][index]["group_id"]}],
                }
                for index, backing in zip(
                    azl_shots, episode["visual_scenes"], strict=True
                )
            )
        except (ValueError, KeyError, OSError):
            issues.append({"code": "EDITING_AZL_LAYOUT_INPUTS_REQUIRED"})
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
                sync_subtitle_entries=authoring.overlay_template_id
                in SYNC_SUBTITLE_TEMPLATES,
                sync_yy_opening_entries=authoring.overlay_template_id
                in (YY_OPENING_TEMPLATES | {PRODUCT_GROUP_ID}),
                sync_presenter_motion_entries=authoring.overlay_template_id
                in {PRESENTER_MOTION_TEMPLATE_ID, PRODUCT_GROUP_ID},
                sync_azl_entries=authoring.overlay_template_id == AZL_TEMPLATE_ID,
                sync_cxbr_entries=authoring.overlay_template_id == CXBR_TEMPLATE_ID,
                sync_unified_entries=authoring.overlay_template_id in UNIFIED_TEMPLATES,
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
        **(
            {"preview_base": options["preview_base"]}
            if options.get("preview_base")
            else {}
        ),
        **(
            {
                **({"applied_highlight_edits": highlights} if highlights else {}),
                **(
                    {"applied_effect_edits": effect_replacements}
                    if effect_replacements
                    else {}
                ),
                **(
                    {"applied_image_edits": image_replacements}
                    if image_replacements
                    else {}
                ),
                "effective_semantic_sha256": hashlib.sha256(
                    semantic.model_dump_json().encode()
                ).hexdigest(),
            }
            if highlights or image_replacements or effect_replacements
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
        if any(row["code"] == BROWSER_ORIGINALS_REQUIRED for row in issues):
            raise EditingFailure(BROWSER_ORIGINALS_REQUIRED)
        if any(row["code"] == BROWSER_BOOT_FONTS_REQUIRED for row in issues):
            raise EditingFailure(BROWSER_BOOT_FONTS_REQUIRED)
        if any(row["code"] == "EDITING_SOUND_INPUTS_REQUIRED" for row in issues):
            raise EditingFailure("EDITING_SOUND_INPUTS_REQUIRED")
        raise EditingFailure("EDITING_NATIVE_INPUTS_REQUIRED")
    if sound_plan is not None:
        atomic_json(root / "audio-plan.json", sound_plan)
    atomic_json(root / "semantic-plan.json", original_semantic.model_dump(mode="json"))
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
    question_shots = [
        i for i, shot in enumerate(episode["shots"]) if question_card_a_shot(shot)
    ]
    numbered_shots = [
        i
        for i, shot in enumerate(episode["shots"])
        if authoring.overlay_template_id == NUMBERED_TEMPLATE_ID
        and shot["group_id"] == NUMBERED_GROUP
    ]
    handoff_shots = [
        i
        for i, shot in enumerate(episode["shots"])
        if authoring.overlay_template_id in TEXT_HANDOFF_TEMPLATES
        and shot["group_id"] == TEXT_HANDOFF_GROUP
    ]
    progress_role_shots = [
        i
        for i, shot in enumerate(episode["shots"])
        if authoring.overlay_template_id in LAYERED_SUBTITLE_TEMPLATES
        and shot["group_id"] in LAYERED_SUBTITLE_ROLE_GROUPS
    ]
    if (
        backdrop_shots
        or question_shots
        or numbered_shots
        or handoff_shots
        or progress_role_shots
    ):
        atomic_json(
            root / "layout-intent.json",
            {
                "sg_s10_backdrop_shots": backdrop_shots,
                "ah_s03_input_a_shots": question_shots,
                **({"numbered_alpha_shots": numbered_shots} if numbered_shots else {}),
                **({"jj_s06_handoff_shots": handoff_shots} if handoff_shots else {}),
                **(
                    {"progress_role_shots": progress_role_shots}
                    if progress_role_shots
                    else {}
                ),
            },
        )
    if continuous_base:
        inset_shots = [
            i
            for i, shot in enumerate(episode["shots"])
            if shot["group_id"] in NATIVE_PORTRAIT_INSETS and shot["rect"] != FULL_FRAME
        ]
        if inset_shots:
            atomic_json(root / "inset-layout-intent.json", {"shots": inset_shots})
    if authoring.overlay_template_id in YY_OPENING_TEMPLATES:
        yy_openings = [
            i
            for i, shot in enumerate(episode["shots"])
            if shot["group_id"] in YY_OPENING_ALL_GROUPS
        ]
        if yy_openings:
            atomic_json(root / YY_OPENING_CAPTION_INTENT, {"shots": yy_openings})
    if azl_shots:
        atomic_json(root / AZL_LAYOUT_INTENT, {"shots": azl_shots})
    if authoring.overlay_template_id == CXBR_TEMPLATE_ID:
        cxbr_shots = [
            index
            for index, shot in enumerate(episode["shots"])
            if shot["group_id"] in CXBR_PURPOSES
        ]
        if cxbr_shots:
            atomic_json(root / CXBR_CAPTION_INTENT, {"shots": cxbr_shots})
    if authoring.overlay_template_id in UNIFIED_TEMPLATES:
        unified_shots = [
            i
            for i, shot in enumerate(episode["shots"])
            if shot["group_id"] in UNIFIED_SCENE_GROUPS
        ]
        if unified_shots:
            atomic_json(root / UNIFIED_CAPTION_INTENT, {"shots": unified_shots})
    atomic_json(root / "episode.json", episode)
    return episode
