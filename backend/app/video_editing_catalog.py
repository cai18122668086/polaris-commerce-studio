"""Full original library metadata; immutable stock and project choices stay separate."""

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from .motion_library import MOTION_SHA256, inside, read_json, sha256
from .motion_library_validation import group_status
from .motion_local_dependencies import DependencyState, dependency_state
from .video_editing_browser_clocks import CARD_GROUP
from .video_editing_contracts import LibraryChoiceSnapshot
from .video_editing_hypit_foreground import FOREGROUND_MATTE
from .video_editing_hypit_label_cards import LABEL_CARD_FONT, LABEL_CARD_GROUP
from .video_editing_hypit_strips import SLANT_GROUP
from .video_editing_judgment import JUDGMENT_BRUSH_FONT, JUDGMENT_GROUP
from .video_editing_line_branch import LINE_BRUSH_FONT, LINE_GROUP
from .video_editing_native_content import WHY_FONT, WHY_GROUP, WHY_PROPS
from .video_editing_overlay_templates import (
    AUTOMATIC_TEMPLATE_DEPENDENCIES,
    QUESTION_CARD_TEMPLATE_ID,
)
from .video_editing_question_card import (
    QUESTION_CARD_A_FONTS,
    QUESTION_CARD_B_FONTS,
    QUESTION_CARD_GROUP,
    question_card_a_input,
)

_MATTING_MODEL = "model-01eb6a29a5c4d8edb30b"
_NATIVE_ENGINE_DEPENDENCIES = {
    JUDGMENT_GROUP: (JUDGMENT_BRUSH_FONT,),
    LINE_GROUP: (LINE_BRUSH_FONT,),
    WHY_GROUP: (WHY_FONT, *WHY_PROPS),
    **{
        gid: dependencies
        for gid, dependencies in AUTOMATIC_TEMPLATE_DEPENDENCIES.items()
        if gid != QUESTION_CARD_GROUP
    },
    SLANT_GROUP: (FOREGROUND_MATTE,),
    LABEL_CARD_GROUP: (LABEL_CARD_FONT,),
    "CXBR01": ("font-43a890795ad133d7",),
    "YYP04": (_MATTING_MODEL,),
    "YYP06": (_MATTING_MODEL,),
    **dict.fromkeys(
        (f"AZL{number:02}" for number in range(1, 8)),
        ("font-aa4560dd8fe56457", _MATTING_MODEL),
    ),
}


def choice_snapshot_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in data.items() if k != "sha256"},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate_choice_snapshot(package: Path, data: dict[str, Any]) -> dict[str, Any]:
    snapshot = LibraryChoiceSnapshot.model_validate(data).model_dump(mode="json")
    if (
        snapshot["library_release"] != MOTION_SHA256
        or choice_snapshot_hash(snapshot) != snapshot["sha256"]
    ):
        raise ValueError("Project library choices do not match their snapshot/release")
    targets = {
        "group": {
            g["id"] for g in read_json(package / "catalog/groups.json")["groups"]
        },
        "bundled_asset": {
            a["id"] for a in read_json(package / "asset-manifest.json")["assets"]
        },
        "external_resource": {
            r["id"]
            for r in read_json(package / "catalog/external-resources.json")["resources"]
        },
    }
    seen = set()
    for note in snapshot["notes"]:
        key = (note["target_kind"], note["target_id"])
        if (
            key in seen
            or note["target_id"] not in targets[note["target_kind"]]
            or not note["reason"].strip()
        ):
            raise ValueError("Unknown, duplicated or empty project library choice")
        seen.add(key)
    return snapshot


def catalog_summary(package: Path, state: Path) -> dict[str, Any]:
    groups = read_json(package / "catalog/groups.json")["groups"]
    assets = read_json(package / "asset-manifest.json")["assets"]
    external = read_json(package / "catalog/external-resources.json")["resources"]
    if len(groups) != 132 or len(assets) != 197 or len(external) != 699:
        raise ValueError("The complete original library is required")
    evidence = [group_status(state, g["id"]) for g in groups]
    statuses = Counter(s["runtime_validation"] for s in evidence)
    return {
        "release": MOTION_SHA256,
        "groups": len(groups),
        "group_kinds": dict(Counter(g["kind"] for g in groups)),
        "runtime": dict(statuses),
        "visual_accepted": sum(s["visual_acceptance"] == "accepted" for s in evidence),
        "bundled_assets": len(assets),
        "bundled_kinds": dict(Counter(a["kind"] for a in assets)),
        "external_references": len(external),
        "external_kinds": dict(Counter(a["kind"] for a in external)),
        "scope": "catalog and concrete sample evidence; not whole-library execution",
    }


def asset_label(asset: dict[str, Any]) -> str:
    faces = asset.get("faces") or []
    return (
        asset.get("name")
        or asset.get("label")
        or (faces[0].get("full_name") or faces[0].get("family") if faces else None)
        or asset.get("path", "").replace("\\", "/").rsplit("/", 1)[-1]
        or asset["id"]
    )


def asset_metadata(
    asset: dict[str, Any], *, bundled: bool, bindings: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        **asset,
        "display_name": asset_label(asset),
        "availability": "packaged" if bundled else "requires_explicit_task_binding",
        **(
            {
                "local_dependency_state": dependency_state(
                    asset, (bindings or {}).get(asset["id"])
                )
            }
            if not bundled and asset["kind"] in {"font", "model"}
            else {}
        ),
        "audio_preview_supported": bundled
        and asset["kind"] in {"sfx", "sfx-processed", "music"},
        "audition_review": "unreviewed",
    }


def audio_asset(package: Path, asset_id: str) -> tuple[dict[str, Any], Path]:
    asset = next(
        (
            a
            for a in read_json(package / "asset-manifest.json")["assets"]
            if a["id"] == asset_id
        ),
        None,
    )
    if not asset or asset["kind"] not in {"sfx", "sfx-processed", "music"}:
        raise LookupError("No bundled audio asset")
    path = inside(package, asset["path"])
    if (
        path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
        or not path.is_file()
        or sha256(path) != asset["sha256"]
    ):
        raise ValueError("Original audio asset bytes changed")
    return asset, path


def template_dependencies(
    package: Path, group: dict[str, Any], bindings: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    external = external_dependencies(package)
    aliases = (
        read_json(package / "catalog/native-relative-assets.json")
        if group.get("backend") == "browser"
        else {}
    )
    return _template_dependencies(
        package,
        group,
        external,
        aliases,
        lambda rid: dependency_state(external[rid], (bindings or {}).get(rid)),
    )


def external_dependencies(package: Path) -> dict[str, dict]:
    return {
        r["id"]: r
        for r in read_json(package / "catalog/external-resources.json")["resources"]
    }


def _template_dependencies(
    package: Path,
    group: dict[str, Any],
    external: dict[str, dict],
    aliases: dict[str, str],
    state_for: Callable[[str], DependencyState],
    *,
    original_input_a: bool = False,
) -> list[dict[str, Any]]:
    references: dict[str, list[str]] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, path + "/" + str(i))
        elif (
            isinstance(value, str)
            and value.startswith("input://")
            and path != "/output"
            and not path.startswith("/output/")
        ):
            # Output references in the historical template are not input media.
            references.setdefault(value[8:], []).append(path)

    template_path = (
        question_card_a_input(package, group)
        if original_input_a
        else package / group["input_template"]
    )
    visit(read_json(template_path), "")
    native_aliases: dict[str, list[str]] = {}
    if group.get("backend") == "browser":
        prefix = group["browser_directory"] + "/"
        for path, value in aliases.items():
            if path.startswith(prefix) and value.startswith("input://"):
                rid = value[8:]
                if external.get(rid, {}).get("kind") == "font":
                    native_aliases.setdefault(rid, []).append(path.removeprefix(prefix))
                    references.setdefault(rid, [])
    for rid in _NATIVE_ENGINE_DEPENDENCIES.get(group["id"], ()):
        if rid in external:
            references.setdefault(rid, [])
    return [
        {
            "id": rid,
            "kind": external.get(rid, {}).get("kind", "unresolved"),
            "display_name": asset_label(external[rid]) if rid in external else rid,
            "input_fields": fields,
            "binding_scope": (
                "current_project_media"
                if external.get(rid, {}).get("kind") == "media"
                else "selectable_original_font"
                if group.get("id") == CARD_GROUP and fields == ["/font"]
                else "engine_font_reference"
                if rid in native_aliases
                else "exact_native_dependency"
            ),
            **(
                {"native_resource_paths": native_aliases[rid]}
                if rid in native_aliases
                else {}
            ),
            "availability": "requires_explicit_task_binding",
            **(
                {"original_rights": external[rid]["rights"]}
                if external.get(rid, {}).get("rights")
                else {}
            ),
            **(
                {"local_dependency_state": state_for(rid)}
                if external.get(rid, {}).get("kind") in {"font", "model"}
                else {}
            ),
        }
        for rid, fields in references.items()
    ]


def original_input_variants(
    package: Path, group: dict, bindings: dict[str, str], evidence: list[dict]
) -> list[dict[str, Any]]:
    if group["id"] != QUESTION_CARD_GROUP:
        return []
    external = external_dependencies(package)
    a_path = question_card_a_input(package, group)
    original_serif_path = read_json(a_path)["fonts"]["chinese"]["path"][6:]
    serif = next(
        asset
        for asset in read_json(package / "asset-manifest.json")["assets"]
        if asset["path"] == original_serif_path
    )
    original_serif = {
        "id": serif["id"],
        "display_name": asset_label(serif),
        "local_dependency_state": dependency_state(
            serif, str(inside(package, serif["path"]))
        ),
    }
    return [
        {
            "id": variant,
            "template_sha256": sha256(template),
            "dependency_fonts": [
                *([original_serif] if variant == "input-A" else []),
                *(
                    {
                        "id": rid,
                        "display_name": asset_label(external[rid]),
                        "local_dependency_state": dependency_state(
                            external[rid], bindings.get(rid)
                        ),
                    }
                    for rid in font_ids
                ),
            ],
            "has_encoded_sample": any(
                row.get("native_branch") == variant
                and row["runtime_validation"] == "sample_rendered"
                for row in evidence
            ),
        }
        for variant, template, font_ids in (
            ("input-A", a_path, QUESTION_CARD_A_FONTS),
            ("input-B", package / group["input_template"], QUESTION_CARD_B_FONTS),
        )
    ]


def unavailable_template_groups(
    template: dict | None, state_for: Callable[[str], DependencyState]
) -> dict[str, list[str]]:
    unavailable = {}
    for slot in (template or {}).get("slots", []):
        gid = slot["group_id"]
        missing = [
            rid
            for rid in AUTOMATIC_TEMPLATE_DEPENDENCIES.get(gid, ())
            if state_for(rid) != "verified"
        ]
        if missing:
            unavailable[gid] = missing
    return unavailable


def planning_runtime_snapshot(
    package: Path, state: Path, bindings: dict[str, str], template: dict | None
) -> dict[str, Any]:
    """Collect portable evidence labels and deduplicate host byte checks."""
    groups = read_json(package / "catalog/groups.json")["groups"]
    external = external_dependencies(package)
    aliases = (
        read_json(package / "catalog/native-relative-assets.json")
        if any(g.get("backend") == "browser" for g in groups)
        else {}
    )

    @cache
    def state_for(rid: str) -> DependencyState:
        return dependency_state(external.get(rid, {}), bindings.get(rid))

    return {
        "version": "tengli.planning-runtime/1",
        "groups": {
            group["id"]: {
                "sample": group_status(state, group["id"])["runtime_validation"],
                "dependencies": [
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "scope": row["binding_scope"],
                        "state": row["local_dependency_state"],
                    }
                    for row in _template_dependencies(
                        package,
                        group,
                        external,
                        aliases,
                        state_for,
                        original_input_a=bool(
                            template
                            and template["id"] == QUESTION_CARD_TEMPLATE_ID
                            and group["id"] == QUESTION_CARD_GROUP
                        ),
                    )
                    if row["kind"] in {"font", "model"}
                ],
            }
            for group in groups
        },
        "unavailable_template_groups": unavailable_template_groups(template, state_for),
    }
