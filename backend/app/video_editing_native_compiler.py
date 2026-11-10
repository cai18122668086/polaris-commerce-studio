"""Fill a freshly authored native recipe; never fall back to historical content.

Recipes are trusted adapter/operator data, NOT model output. They must provide
the current design and all non-anchor native parameters. This module does not
invent a universal renderer or silently replace an unsupported original group.
"""

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .motion_library import MOTION_SHA256, atomic_json, inside, read_json, sha256
from .motion_local_dependencies import dependency_state, local_dependencies
from .motion_parameter_contracts import (
    SHIFTED_GEOMETRY_EVENTS,
    SILHOUETTE_GROUPS,
    SILHOUETTE_PATHS,
    input_contract,
)
from .video_editing_browser_clocks import (
    CARD_GROUP,
    FRUIT_LIST_GROUP,
    LIVE_BROWSER_SOURCE_FIELDS,
    LIVE_SPLIT_GROUPS,
    SPLIT_GROUPS,
    SPLIT_HORIZONTAL,
    card_font_evidence,
    compile_card_clock,
    compile_fruit_list_clock,
    compile_split_clock,
)
from .video_editing_browser_live import (
    CARD_LIVE_PREFIX,
    FRUIT_LIST_PREFIX,
    card_live_clock,
)
from .video_editing_browser_rotation import (
    ROTATION_GROUP,
    ROTATION_MATTE,
    compile_rotation_clock,
    rotation_source_clock,
)
from .video_editing_collage_scene import (
    COLLAGE_GROUP,
    COLLAGE_SOURCE,
    collage_image_slots,
    validate_collage_anchors,
    validate_collage_images,
)
from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_crowd_scene import (
    CROWD_FULL_FRAME,
    CROWD_GROUP,
    CROWD_PRESENTER,
    crowd_image_slots,
    validate_crowd_anchors,
    validate_crowd_images,
)
from .video_editing_hypit import (
    PICTURE_PROFILE,
    compile_picture_clocks,
)
from .video_editing_hypit_chart import FLOW_CHART_DESIGN, compile_flow_chart
from .video_editing_hypit_foreground import FOREGROUND_MATTE
from .video_editing_hypit_strips import (
    FLOW_GROUP,
    LIVE_STAGE_GROUPS,
    SLANT_FOREGROUND,
    SLANT_GROUP,
    SLANT_IMAGES,
    SLANT_PROFILE,
    STAGGER_GROUPS,
    STRIP_SIDECAR,
    STRIP_TEXT,
    compile_flow_plate,
    compile_strips,
    strip_config_sha256,
)
from .video_editing_judgment import (
    JUDGMENT_BACKGROUND,
    JUDGMENT_BRUSH_FONT,
    JUDGMENT_GROUP,
)
from .video_editing_line_branch import (
    LINE_BRUSH_FONT,
    LINE_GROUP,
    LINE_HAND_PATH,
    LINE_HAND_PREFIX,
    LINE_SHEET_FRAMES,
    line_template,
    stage_line_sheet,
)
from .video_editing_media_clocks import compile_media_clocks
from .video_editing_native_content import (
    CHAPTER_PATH,
    FILM_FEEDBACK_GROUP,
    NUMBER_GROUP,
    PACKAGE_GROUP,
    ROLE_CHAIN_GROUP,
    WHY_FONT,
    WHY_GROUP,
    YEAR_GROUP,
    YEAR_PATH,
    automatic_translation_labels,
    chapter_ordinal,
    film_feedback_entries,
    live_package_template,
    number_glyphs,
    package_entries,
    role_scene_chain,
    translation_labels,
    why_template,
    why_word_bindings,
    year_glyphs,
)
from .video_editing_paper_typewriter import (
    PAPER_GROUP,
    paper_character_times,
)
from .video_editing_question_branch import (
    QUESTION_BACKGROUND,
    QUESTION_BRANCH,
    QUESTION_FONT,
    QUESTION_GROUP,
    question_variant_template,
)
from .video_editing_question_card import (
    QUESTION_CARD_A_DESIGN,
    QUESTION_CARD_ENGLISH,
    automatic_question_card_gloss,
    question_card_a_input,
    question_card_gloss,
)
from .video_editing_role_scene import bind_role_scene
from .video_editing_story_panels import TRIPTYCH, triptych_template
from .video_editing_unified_alpha import (
    ALPHA_GROUPS,
    ALPHA_PRESENTER,
    alpha_presenter_directory,
    alpha_source_clock,
)
from .video_editing_unified_scenes import (
    PRESENTER_VIDEO_GROUPS,
    UNIFIED_DESIGN_ID,
    unified_presenter_template,
)
from .video_editing_word_bindings import word_bindings


def _parent(value: Any, path: str) -> tuple[Any, str | int]:
    if not path.startswith("/"):
        raise ValueError("Native field must be a declared JSON pointer")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value, int(parts[-1]) if isinstance(value, list) else parts[-1]


def _get(value: dict, path: str) -> Any:
    parent, key = _parent(value, path)
    return parent[key]


def set_native_field(value: dict, path: str, assigned: Any) -> None:
    parent, key = _parent(value, path)
    # Never create arbitrary configuration paths on behalf of a model.
    parent[key]  # Existing key/index required.
    parent[key] = assigned


def _same_shape(template: Any, current: Any) -> bool:
    if isinstance(template, dict):
        return (
            isinstance(current, dict)
            and template.keys() == current.keys()
            and all(_same_shape(v, current[k]) for k, v in template.items())
        )
    if isinstance(template, list):
        return (
            isinstance(current, list)
            and len(template) == len(current)
            and all(_same_shape(a, b) for a, b in zip(template, current, strict=True))
        )
    return not isinstance(current, (dict, list))


def _bundled_font(package: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.startswith("pkg://"):
        raise ValueError("Select an original bundled font explicitly")
    font = next(
        (
            asset
            for asset in read_json(package / "asset-manifest.json")["assets"]
            if asset["kind"] == "font" and asset["path"] == value[6:]
        ),
        None,
    )
    if not font:
        raise ValueError("Selected font is absent from the original bundle")
    path = inside(package, font["path"])
    if sha256(path) != font["sha256"]:
        raise ValueError("Selected original font bytes changed")
    return path


def compile_native_job(
    package: Path,
    root: Path,
    beat: SemanticBeat,
    transcript: Transcript,
    recipe: dict[str, Any],
    asset_files: dict[str, dict[str, Any]],
    *,
    native_bindings_file: Path | None = None,
    component_validation: bool = False,
) -> dict[str, Any]:
    """Return a schema-admitted original job plus traceable measured bindings.

    This does not declare native execution, factual correctness or acceptance.
    A recipe without a required native input fails rather than using a demo.
    """
    root = root.resolve()
    if root.is_relative_to(package.resolve()):
        raise ValueError("Native instance must remain outside the original library")
    if (root / "job.json").exists():
        raise FileExistsError(
            "Preserve the previous compiled instance; choose a new one"
        )
    groups = {g["id"]: g for g in read_json(package / "catalog/groups.json")["groups"]}
    group = groups[beat.group_id]
    config = copy.deepcopy(recipe["config"])
    question_card_a = recipe.get("design_id") == QUESTION_CARD_A_DESIGN
    branch = config.get("branch") if beat.group_id == QUESTION_GROUP else None
    if beat.group_id == QUESTION_GROUP and branch not in (QUESTION_BRANCH, "smoke"):
        raise ValueError("Select an original W-R18 branch")
    question_variant = beat.group_id == QUESTION_GROUP and branch == QUESTION_BRANCH
    embedded_caption = not question_variant or config["content"].get("captions") != []
    live_question_background = (
        question_variant and QUESTION_BACKGROUND in config["media"]
    )
    live_package_presenter = (
        beat.group_id == PACKAGE_GROUP
        and config.get("media", {}).get("presenter", {}).get("kind") == "video"
    )
    current_unified_presenter = (
        beat.group_id in PRESENTER_VIDEO_GROUPS
        and config.get("media", {}).get("presenter", {}).get("kind") == "video"
    )
    live_paper = recipe.get("paper_typewriter_live", False)
    live_crowd = recipe.get("crowd_live_source", False)
    live_collage = recipe.get("collage_live_source", False)
    if type(live_collage) is not bool or (
        live_collage
        and (
            beat.group_id != COLLAGE_GROUP
            or config["media"]["background"]["end_policy"] != "error"
            or recipe.get("media_clocks")
            != [{"media_path": COLLAGE_SOURCE, "policy": "transcript_source_window"}]
        )
    ):
        raise ValueError("Original collage needs a verified current background")
    if type(live_crowd) is not bool or (
        live_crowd
        and (
            beat.group_id != CROWD_GROUP
            or config["media"]["presenter"]["crop"] != CROWD_FULL_FRAME
            or config["media"]["presenter"]["end_policy"] != "error"
            or recipe.get("media_clocks")
            != [{"media_path": CROWD_PRESENTER, "policy": "transcript_source_window"}]
        )
    ):
        raise ValueError("Original crowd needs its full-frame live presenter")
    new_alpha = recipe.get("unified_alpha_presenter", False)
    live_alpha = live_paper or new_alpha
    if (
        type(live_paper) is not bool
        or type(new_alpha) is not bool
        or (live_paper and beat.group_id != PAPER_GROUP)
        or (new_alpha and beat.group_id not in ALPHA_GROUPS - {PAPER_GROUP})
        or live_alpha
        and (
            config["layout"]["mode"] != "adaptive"
            or config["media"]["presenter"].get("alpha") is not True
            or recipe.get("media_clocks")
        )
    ):
        raise ValueError("Moving foreground needs its original adaptive alpha slot")
    triptych_slots = (
        {
            i
            for i, clip in enumerate(config.get("media", {}).get("clips", []))
            if i in {1, 2} and clip.get("kind") == "video"
        }
        if beat.group_id == TRIPTYCH
        else set()
    )
    line_art = beat.group_id == LINE_GROUP and "hand_sequence" in config["media"]
    embedded_line_caption = not line_art or config["content"].get("captions") != []
    website_judgment = (
        beat.group_id == JUDGMENT_GROUP and config["content"].get("captions") == []
    )
    why_props = beat.group_id == WHY_GROUP and "question_props" in config["media"]
    embedded_why_caption = not why_props or config["content"].get("captions") != []
    contract = input_contract(
        package,
        group,
        branch=branch,
        embedded_question_caption=embedded_caption,
        live_question_background=live_question_background,
        live_package_presenter=live_package_presenter,
        current_line_art=line_art,
        embedded_line_caption=embedded_line_caption,
        embedded_judgment_caption=not website_judgment,
        current_why_props=why_props,
        embedded_why_caption=embedded_why_caption,
        original_input_a=question_card_a,
        current_unified_presenter=current_unified_presenter,
        triptych_video_slots=triptych_slots,
    )
    if (
        recipe.get("version") != "tengli.native-recipe/1"
        or recipe.get("release") != MOTION_SHA256
        or recipe.get("group_id") != beat.group_id
        or recipe.get("template_sha256") != contract["template_sha256"]
        or recipe.get("schema_sha256") != contract["schema_sha256"]
    ):
        raise ValueError("Recipe does not match this exact original group release")
    if not recipe.get("design_id") or not recipe.get("design_reason"):
        raise ValueError("A current episode design decision is required")
    template = read_json(
        question_card_a_input(package, group)
        if question_card_a
        else package / group["input_template"]
    )
    if question_card_a:
        if beat.relation != "question" or config.get("fonts") != template["fonts"]:
            raise ValueError(
                "AH-S03 input A requires a spoken question and its exact fonts"
            )
        _bundled_font(package, config["fonts"]["chinese"]["path"])
    if live_package_presenter:
        template = live_package_template(template)
        if config.get("layout", {}).get("mode") != "native":
            raise ValueError("Keep the original single-line package label fit")
    if current_unified_presenter:
        template = unified_presenter_template(template)
        if config["media"]["presenter"]["end_policy"] != "error":
            raise ValueError(
                "Keep the measured presenter moving throughout the original scene"
            )
    if triptych_slots:
        template = triptych_template(template, triptych_slots)
    if line_art:
        template = line_template(template, embedded_caption=embedded_line_caption)
        hand = config["media"]["hand_sequence"]
        if hand != {**template["media"]["hand_sequence"], "path": None}:
            raise ValueError(
                "Preserve the original 24-frame transparent line hand clock"
            )
    if why_props:
        template = why_template(template, embedded_caption=embedded_why_caption)
        if (
            beat.relation != "question"
            or config["media"]["presenter"]["end_policy"] != "error"
            or recipe.get("media_clocks")
            != [
                {
                    "media_path": "/media/presenter/path",
                    "policy": "transcript_source_window",
                }
            ]
            or config["media"]["question_props"]
            != [{"kind": "image", "path": None, "alpha": True}] * 2
        ):
            raise ValueError("W-R17 needs a spoken question, two props and live source")
    if question_variant:
        if beat.relation != "question":
            raise ValueError("W-R18 question branch requires a spoken question beat")
        template = question_variant_template(
            template,
            embedded_caption=embedded_caption,
            live_background=live_question_background,
        )
    if website_judgment:
        template["content"]["captions"] = []
        if (
            beat.relation != "contrast"
            or config["media"]["background"]["end_policy"] != "error"
            or recipe.get("media_clocks")
            != [
                {
                    "media_path": JUDGMENT_BACKGROUND,
                    "policy": "transcript_source_window",
                }
            ]
        ):
            raise ValueError(
                "W-R14 requires a spoken comparison and live original source"
            )
    if beat.group_id in SILHOUETTE_GROUPS:
        slots = [
            {"kind": "image", "alpha": True, "path": None} for _ in SILHOUETTE_PATHS
        ]
        if config.get("media", {}).get("silhouettes") != slots:
            raise ValueError(
                f"{beat.group_id} needs seven explicit native alpha image slots"
            )
        template["media"]["silhouettes"] = slots
    picture_variant = (
        contract.get("native_profile") == PICTURE_PROFILE
        and config.get("profile") == PICTURE_PROFILE
    )
    strip_variant = group["id"] in STAGGER_GROUPS
    live_stage = recipe.get("hypit_live_stage", False)
    if type(live_stage) is not bool or (
        live_stage and beat.group_id not in LIVE_STAGE_GROUPS
    ):
        raise ValueError(
            "Live Hypit stage needs the original strip or price-card canvas"
        )
    if strip_variant and (
        config.get("attributes") != {} or config.get("fonts") != template["fonts"]
    ):
        raise ValueError("Keep original Hypit fonts and schema-owned attributes")
    if group["backend"] == "hypit" and not (picture_variant or strip_variant):
        raise ValueError(
            "The original classic Hypit schema rejects fresh attribute authoring"
        )
    if not picture_variant and not _same_shape(template, config):
        raise ValueError(
            "This recipe changes native field/array topology; "
            "an explicit variant authoring contract is required"
        )
    if question_variant and any(
        slot["end_policy"] != "error" for slot in config["media"].values()
    ):
        raise ValueError("W-R18 question footage cannot loop or hold")
    decisions = recipe.get("parameter_decisions", {})
    placeholders = recipe.get("placeholders", [])
    if len(placeholders) != len(set(placeholders)):
        raise ValueError("Duplicate recipe placeholder")
    native = word_bindings(beat, transcript, contract, set(asset_files))
    if live_crowd:
        validate_crowd_anchors(beat, native)
        selected = {row["path"]: row["asset_id"] for row in native["media"]}
        files = {asset_id: asset_files[asset_id] for asset_id in selected.values()}
        validate_crowd_images(
            selected,
            {asset_id: row["sha256"] for asset_id, row in files.items()},
            crowd_image_slots(files),
        )
    if live_collage:
        validate_collage_anchors(beat, native, transcript)
        selected = {row["path"]: row["asset_id"] for row in native["media"]}
        files = {asset_id: asset_files[asset_id] for asset_id in selected.values()}
        validate_collage_images(
            selected,
            {asset_id: row["sha256"] for asset_id, row in files.items()},
            collage_image_slots(files),
        )
    if beat.group_id == ROLE_CHAIN_GROUP:
        native["role_scene_chain"] = (
            bind_role_scene(beat, native, transcript, asset_files)
            if recipe["design_id"] == UNIFIED_DESIGN_ID
            else role_scene_chain(native, asset_files)
        )
    if live_package_presenter:
        native["package_entries"] = package_entries(native, asset_files)
    if beat.group_id in SILHOUETTE_GROUPS:
        silhouette_ids = {
            row["asset_id"]
            for row in native["media"]
            if row["path"] in SILHOUETTE_PATHS
        }
        if len(silhouette_ids) != len(SILHOUETTE_PATHS) or any(
            asset_files[aid].get("kind") != "image"
            or asset_files[aid].get("source") != "project_upload"
            for aid in silhouette_ids
        ):
            raise ValueError("Bind seven distinct current project silhouette images")
    if (
        group["id"] in SHIFTED_GEOMETRY_EVENTS
        and config.get("events", {}).get("shift_frames", 0) != 0
        and any(
            event["path"].startswith("/style/geometry/") for event in native["events"]
        )
    ):
        raise ValueError("Word-bound scene geometry requires zero native shift_frames")
    live_cards = recipe.get("browser_live_background", False)
    split_live = recipe.get("browser_split_live_presenter", False)
    if type(split_live) is not bool or (
        split_live and (group["id"] not in LIVE_SPLIT_GROUPS or live_cards)
    ):
        raise ValueError("Live split presenter requires its original browser group")
    if type(live_cards) is not bool or (
        live_cards
        and (
            group["id"] not in LIVE_BROWSER_SOURCE_FIELDS or recipe.get("media_clocks")
        )
    ):
        raise ValueError("Live browser background requires a supported original group")
    if live_cards:
        media_clocks: dict[str, float] = {}
        clock_receipts = [card_live_clock(package, native, asset_files, transcript)]
    elif group["id"] == ROTATION_GROUP or split_live:
        if recipe.get("media_clocks"):
            raise ValueError(
                "Original browser scene uses its measured presenter window"
            )
        media_clocks = {}
        clock_receipts = [
            rotation_source_clock(native, asset_files, transcript, split=split_live)
        ]
    elif picture_variant:
        if recipe.get("media_clocks"):
            raise ValueError("Hypit tracks use the measured shot source window")
        media_clocks, clock_receipts = compile_picture_clocks(
            package, config, native, asset_files, transcript, beat
        )
    elif group["id"] == SLANT_GROUP:
        selected = {row["path"]: row["asset_id"] for row in native["media"]}
        first_words = {row["path"]: row["token_ids"][0] for row in native["text"]}
        if (
            beat.relation != "parallel"
            or recipe.get("media_clocks")
            or len(beat.relation_items) != 3
            or any(
                item.native_text_paths != [text_path]
                or item.native_media_paths != [image_path]
                or item.asset_ids != [selected.get(image_path)]
                or item.first_token_id != first_words.get(text_path)
                for item, text_path, image_path in zip(
                    beat.relation_items, STRIP_TEXT, SLANT_IMAGES, strict=True
                )
            )
        ):
            raise ValueError(
                "Slant cards use three spoken items and the original presenter"
            )
        media_clocks = {}
        clock_receipts = [
            compile_flow_plate(
                native,
                asset_files,
                transcript,
                media_path=SLANT_FOREGROUND,
                profile_id=SLANT_PROFILE,
            )
        ]
    elif group["id"] == FLOW_GROUP or live_stage:
        if group["id"] == FLOW_GROUP and recipe["design_id"] == FLOW_CHART_DESIGN:
            native["flow_chart"] = compile_flow_chart(
                beat, native, transcript, STRIP_TEXT
            )
        elif group["id"] == FLOW_GROUP and not component_validation:
            raise ValueError("Hypit flow labels still require fact-grounded chart data")
        if recipe.get("media_clocks"):
            raise ValueError("Hypit plate uses the measured moving source window")
        media_clocks = {}
        clock_receipts = [
            compile_flow_plate(native, asset_files, transcript, live_stage=live_stage)
        ]
    elif live_alpha:
        media_clocks = {}
        clock_receipts = [alpha_source_clock(beat, native, transcript, asset_files)]
        if live_paper:
            native["paper_character_times"] = paper_character_times(
                beat, native, transcript
            )
    else:
        media_clocks, clock_receipts = compile_media_clocks(
            package,
            group,
            contract,
            native,
            recipe.get("media_clocks", []),
            asset_files,
            transcript,
            config,
        )
    native["media_clocks"] = clock_receipts
    if "price_card_layout" in recipe and not strip_variant:
        raise ValueError("Price-card typography needs the audited Hypit input contract")
    if "hypit_slant_glosses" in recipe and group["id"] != SLANT_GROUP:
        raise ValueError("Slant card glosses need the original slant card group")
    strip = (
        compile_strips(
            package,
            group,
            native,
            asset_files,
            price_card_layout=recipe.get("price_card_layout"),
            live_stage=live_stage,
            slant_glosses=recipe.get("hypit_slant_glosses"),
            flow_chart=native.get("flow_chart"),
        )
        if strip_variant
        else None
    )
    website_paths = {
        row["path"] for row in contract["fields"] if row.get("binding_surface")
    }
    assignments = (
        {
            row["path"]: row["text"]
            for row in native["text"]
            if row["path"] not in website_paths
        }
        | {
            row["path"]: row["value"]
            for row in native["events"]
            if row["path"] not in website_paths
        }
        | media_clocks
    )
    if beat.group_id == FILM_FEEDBACK_GROUP:
        feedback = film_feedback_entries(
            native, asset_files, recipe.get("film_feedback")
        )
        assignments.update({row["path"]: row["likes"] for row in feedback})
        native["film_feedback"] = feedback
    if "chapter_start_token_ids" in recipe:
        if CHAPTER_PATH in assignments:
            raise ValueError(
                "Choose either a spoken ordinal or a saved chapter outline"
            )
        chapter = chapter_ordinal(beat, transcript, recipe["chapter_start_token_ids"])
        assignments[CHAPTER_PATH] = chapter["display_text"]
        native["chapter"] = chapter
    if group["id"] == NUMBER_GROUP:
        readings = number_glyphs(native)
        assignments.update({row["path"]: row["display_text"] for row in readings})
        native["number_glyphs"] = readings
    if group["id"] == YEAR_GROUP:
        year = year_glyphs(native)
        assignments[YEAR_PATH] = year["display_text"]
        native["year_glyphs"] = year
    if "translation_labels" in recipe:
        if beat.translation_gloss is not None and recipe[
            "translation_labels"
        ] != automatic_translation_labels(beat, native):
            raise ValueError(
                "Native translations differ from the frozen planning glosses"
            )
        translations = translation_labels(native, recipe["translation_labels"])
        if beat.translation_gloss is not None:
            for row in translations:
                row["origin"] = "tengli_planner"
        assignments.update({row["path"]: row["display_text"] for row in translations})
        native["translation_labels"] = translations
    elif beat.translation_gloss is not None:
        raise ValueError("Native translations require their corresponding recipe")
    if question_card_a:
        authored = recipe.get("question_card_gloss")
        if (
            beat.question_gloss is not None
            and authored != automatic_question_card_gloss(beat, native, transcript)
        ):
            raise ValueError("AH-S03 A recipe differs from the frozen planning gloss")
        gloss = question_card_gloss(native, authored, transcript)
        if beat.question_gloss is not None:
            gloss["origin"] = "tengli_planner"
        assignments[QUESTION_CARD_ENGLISH] = gloss["display_text"]
        native["question_gloss"] = gloss
    elif beat.question_gloss is not None:
        raise ValueError("English question gloss requires the original AH-S03 A recipe")
    if why_props:
        question = why_word_bindings(native, asset_files)
        assignments[question["path"]] = question["display_text"]
        native["question_gloss"] = question
    browser_clock = None
    browser_font = None
    if group["id"] == CARD_GROUP:
        word_entry = recipe.get("browser_word_entry", False)
        if type(word_entry) is not bool:
            raise ValueError("Browser word entry must be a trusted boolean option")
        keyframes, browser_clock = compile_card_clock(
            package, group, template, config, native, word_entry=word_entry
        )
        assignments.update(keyframes)
        native["browser_clock"] = browser_clock
    omitted = recipe.get("empty_text", {})
    for path, reason in omitted.items():
        if (
            path not in contract["text_paths"]
            or path in website_paths
            or not isinstance(reason, str)
            or not reason
        ):
            raise ValueError("Empty text requires a declared native field and reason")
        if path in assignments:
            raise ValueError("Native text is both assigned and omitted")
        assignments[path] = ""
    resources = {}
    dependency_rows = {
        r["id"]: r
        for r in read_json(package / "catalog/external-resources.json")["resources"]
    }
    direct = recipe.get("dependency_bindings", {})
    dependency_ids = recipe.get("dependency_ids", [])
    if (
        not isinstance(dependency_ids, list)
        or any(not isinstance(rid, str) for rid in dependency_ids)
        or len(set(dependency_ids)) != len(dependency_ids)
        or set(dependency_ids) & set(direct)
    ):
        raise ValueError("Choose a single explicit binding per original dependency")
    registered = local_dependencies(native_bindings_file) if dependency_ids else {}
    if set(dependency_ids) - set(registered):
        raise ValueError("Selected original dependency is not registered on this host")
    dependencies = {**direct, **{rid: registered[rid] for rid in dependency_ids}}
    if group["id"] == SLANT_GROUP and FOREGROUND_MATTE not in dependencies:
        raise ValueError("Bind the original slant card presenter matte")
    if live_alpha and FOREGROUND_MATTE not in dependencies:
        raise ValueError("Bind the original unified presenter matte")
    if question_variant and QUESTION_FONT not in dependencies:
        raise ValueError("Bind the original W-R18 question brush font")
    if group["id"] == JUDGMENT_GROUP and JUDGMENT_BRUSH_FONT not in dependencies:
        raise ValueError("Bind the original W-R14 editable brush font")
    if group["id"] == LINE_GROUP and LINE_BRUSH_FONT not in dependencies:
        raise ValueError("Bind the original W-R11 editable brush font")
    if why_props and WHY_FONT not in dependencies:
        raise ValueError("Bind the original W-R17 Arial dependency")
    for rid, declared_path in dependencies.items():
        identity = dependency_rows.get(rid, {})
        source = Path(declared_path).resolve()
        if dependency_state(identity, str(source)) != "verified":
            raise ValueError(
                "Original font/model dependency bytes do not match: " + rid
            )
        resources[rid] = str(source)
    for row in native["media"]:
        asset = asset_files[row["asset_id"]]
        source = Path(asset["path"]).resolve()
        if not source.is_file() or sha256(source) != asset["sha256"]:
            raise ValueError("Current project material is missing or changed")
        prefix = (
            CARD_LIVE_PREFIX
            if live_cards and row["path"] == clock_receipts[0]["media_path"]
            else "tengli-"
        )
        if group["id"] == FRUIT_LIST_GROUP and row["path"] == "/presenter":
            prefix = FRUIT_LIST_PREFIX
        rid = prefix + asset["sha256"][:24]
        if (group["id"] == ROTATION_GROUP or split_live) and row[
            "path"
        ] == "/presenter":
            rid = clock_receipts[0]["binding_id"]
        if live_alpha and row["path"] == ALPHA_PRESENTER:
            rid = clock_receipts[0]["binding_id"]
            resources[rid + "-source"] = str(source)
            source = root / alpha_presenter_directory(beat.group_id)
        if line_art and row["path"] == LINE_HAND_PATH:
            if asset.get("kind") != "image" or asset.get("source") != "project_upload":
                raise ValueError("Bind a current registered hand sheet image")
            sequence, digest = stage_line_sheet(root, source, asset["sha256"])
            shot_key = hashlib.sha256(beat.id.encode()).hexdigest()[:12]
            rid = f"{LINE_HAND_PREFIX}{digest[:24]}-{shot_key}"
            resources[rid + "-frames"] = str(sequence)
            native["line_hand_sequence"] = {
                "sheet_asset_id": row["asset_id"],
                "sheet_sha256": asset["sha256"],
                "sequence_binding_sha256": digest,
                "frames": LINE_SHEET_FRAMES,
                "fps": 30,
            }
        resources[rid] = str(source)
        assignments[row["path"]] = "input://" + rid
    retained_glyphs = {}
    for field in contract["fields"]:
        if field["path"] in website_paths:
            continue
        if field.get("optional_parent") and field["optional_parent"] not in config:
            continue
        path, category = field["path"], field["category"]
        value = _get(config, path)
        if category in {
            "text",
            "event",
            "resource",
            "native_keyframe_clock",
            "hypit_source_start",
            "evidence_bound_comment_likes",
        }:
            if path not in assignments or path not in placeholders or value is not None:
                raise ValueError(
                    "Fresh native content/event/media needs an empty bound slot: "
                    + path
                )
        elif category == "selected_bundled_font":
            if not decisions.get("font") and not decisions.get(path):
                raise ValueError("Record the native font choice: " + path)
            _bundled_font(package, value)
        elif category == "native_dependency":
            if not decisions.get(path.split("/")[1]) and not decisions.get(path):
                raise ValueError("Record the native font/model choice: " + path)
            is_card_font = group["id"] == CARD_GROUP and path == "/font"
            if is_card_font and isinstance(value, str) and value.startswith("pkg://"):
                browser_font = _bundled_font(package, value)
            elif (
                not isinstance(value, str)
                or not value.startswith("input://")
                or value[8:] not in resources
            ):
                raise ValueError(
                    "Exact original font/model dependency is not bound: " + path
                )
            elif is_card_font:
                if value != template["font"] or value[8:] not in dependencies:
                    raise ValueError(
                        "Bind the original browser card font or select a bundled font"
                    )
                browser_font = Path(resources[value[8:]])
        elif category == "numeric_content_requires_grounding":
            raise ValueError(
                "Native numeric content needs a fact-grounded recipe: " + path
            )
        elif category == "native_media_key":
            if value != _get(template, path) or not decisions.get("content"):
                raise ValueError(
                    "Preserve the original named media slot mapping: " + path
                )
        elif category == "original_design_glyph":
            if value != _get(template, path) or not decisions.get(path):
                raise ValueError(
                    "Preserve and document the original design glyph: " + path
                )
            retained_glyphs[path] = value
        elif category == "output_owned_by_compiler":
            set_native_field(config, path, str(root / "renders/component.mp4"))
        elif category == "clock_owned_by_compiler":
            if path.startswith("/media/"):
                if (
                    path not in media_clocks
                    or value is not None
                    or path not in placeholders
                ):
                    raise ValueError(
                        "Native media time requires an empty measured clock slot: "
                        + path
                    )
                continue
            key = path.rsplit("/", 1)[-1]
            duration = (native["clock"]["end_ms"] - native["clock"]["start_ms"]) / 1000
            if key == "frames":
                set_native_field(
                    config, path, math.ceil(duration * contract["native_fps"])
                )
            elif key in {"duration", "duration_seconds"} and not path.startswith(
                "/media/"
            ):
                set_native_field(config, path, duration)
            elif key == "fps":
                if value != contract["native_fps"]:
                    raise ValueError(
                        "Recipe frame rate differs from the original contract"
                    )
            elif not decisions.get(path):
                raise ValueError(
                    "Media clock needs a current source-range decision: " + path
                )
        elif not decisions.get(path.split("/")[1]) and not decisions.get(path):
            raise ValueError(
                "Record the current native parameter/design choice: " + path
            )
    if set(placeholders) != set(assignments):
        raise ValueError("Every fresh recipe placeholder must have one current binding")
    for path, value in assignments.items():
        if _get(config, path) is not None:
            raise ValueError("A binding would overwrite existing native content")
        set_native_field(config, path, value)
    if live_alpha:
        clock = clock_receipts[0]
        config["media"]["presenter"].update(
            kind="frame_sequence",
            fps=clock["fps"],
            frames=clock["frames"],
            end_policy="error",
        )
    if live_paper:
        for row, times in zip(
            config["content"]["rows"], native["paper_character_times"], strict=True
        ):
            row["char_times"] = times
    if browser_clock is not None:
        if browser_font is None:
            raise ValueError("Browser card font is not bound")
        browser_clock.update(card_font_evidence(browser_font, config))
    elif group["id"] in SPLIT_GROUPS:
        browser_clock = compile_split_clock(package, group, config, resources)
        if split_live:
            if config["background"] is not None or (
                group["id"] == SPLIT_HORIZONTAL and ROTATION_MATTE not in resources
            ):
                raise ValueError(
                    "Live split needs its original background and matte policy"
                )
            if group["id"] == SPLIT_HORIZONTAL and any(
                len(item["label"]) > 2 for item in config["items"]
            ):
                raise ValueError(
                    "Horizontal labels must fit left of the original portrait"
                )
            browser_clock["presenter_clock"] = clock_receipts[0]
        native["browser_clock"] = browser_clock
    elif group["id"] == FRUIT_LIST_GROUP:
        if beat.relation != "parallel":
            raise ValueError("Use the original fruit list for three parallel items")
        browser_clock = compile_fruit_list_clock(
            package, group, config, resources, native, asset_files
        )
        native["browser_clock"] = browser_clock
    elif group["id"] == ROTATION_GROUP:
        if beat.relation != "parallel":
            raise ValueError("Use the original rotating cards for three parallel items")
        browser_clock = compile_rotation_clock(
            package, group, config, resources, native, asset_files
        )
        native["browser_clock"] = browser_clock
    schema = read_json(package / group["input_schema"])
    Draft202012Validator(schema).validate(config)
    job = {
        "schema": "commercial-talk-job/1",
        "group_id": beat.group_id,
        "config": config,
        "output": str(root / "renders/component.mp4"),
    }
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "job.json", job)
    bindings: dict[str, Any] = {"resources": resources, "tools": {}}
    strip_digest = None
    if strip is not None:
        sidecar = root / STRIP_SIDECAR
        atomic_json(sidecar, {**strip, "config_sha256": strip_config_sha256(config)})
        strip_digest = sha256(sidecar)
        bindings["tengli_hypit_strips"] = {"component": strip_digest}
    atomic_json(root / "bindings.json", bindings)
    atomic_json(root / "word-bindings.json", native)
    atomic_json(root / "native-recipe.json", recipe)
    atomic_json(
        root / "compile-receipt.json",
        {
            "version": "tengli.native-compilation/1",
            "group_id": beat.group_id,
            "beat_id": beat.id,
            "design_id": recipe["design_id"],
            "design_reason": recipe["design_reason"],
            "parameter_decisions": decisions,
            "release": MOTION_SHA256,
            "template_sha256": contract["template_sha256"],
            "schema_sha256": contract["schema_sha256"],
            "source_sha256": transcript.source_sha256,
            "audio_sha256": transcript.audio_sha256,
            "recipe_sha256": sha256(root / "native-recipe.json"),
            "job_sha256": sha256(root / "job.json"),
            "word_bindings_sha256": sha256(root / "word-bindings.json"),
            "media_clocks": clock_receipts,
            **({"retained_design_glyphs": retained_glyphs} if retained_glyphs else {}),
            **(
                {
                    key: native[key]
                    for key in (
                        "chapter",
                        "number_glyphs",
                        "year_glyphs",
                        "translation_labels",
                        "role_scene_chain",
                        "flow_chart",
                        "package_entries",
                        "film_feedback",
                        "line_hand_sequence",
                        "paper_character_times",
                        "question_gloss",
                    )
                    if key in native
                }
            ),
            **({"local_dependency_ids": dependency_ids} if dependency_ids else {}),
            **({"native_profile": PICTURE_PROFILE} if picture_variant else {}),
            **({"native_branch": branch} if branch is not None else {}),
            **(
                {
                    "website_sidecar_profile": contract["website_sidecar_profile"],
                    "sidecar_sha256": strip_digest,
                }
                if strip_digest
                else {}
            ),
            **({"browser_clock": browser_clock} if browser_clock else {}),
            "schema_validation": "passed",
            "native_execution": "not_performed",
            "semantic_review": "unreviewed",
            "visual_review": "unreviewed",
            "hearing_review": "unreviewed",
        },
    )
    return job
