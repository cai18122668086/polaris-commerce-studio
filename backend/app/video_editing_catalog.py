"""Full original library metadata; immutable stock and project choices stay separate."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .motion_library import MOTION_SHA256, inside, read_json, sha256
from .motion_library_validation import group_status
from .video_editing_browser_clocks import CARD_GROUP
from .video_editing_contracts import LibraryChoiceSnapshot

_SCENE_ENGINE_DEPENDENCIES = {
    "CXBR01": ("font-43a890795ad133d7",),
    **dict.fromkeys(
        (f"AZL{number:02}" for number in range(1, 8)),
        ("font-aa4560dd8fe56457", "model-01eb6a29a5c4d8edb30b"),
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


def asset_metadata(asset: dict[str, Any], *, bundled: bool) -> dict[str, Any]:
    return {
        **asset,
        "display_name": asset_label(asset),
        "availability": "packaged" if bundled else "requires_explicit_task_binding",
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


def template_dependencies(package: Path, group: dict[str, Any]) -> list[dict[str, Any]]:
    external = {
        r["id"]: r
        for r in read_json(package / "catalog/external-resources.json")["resources"]
    }
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

    visit(read_json(package / group["input_template"]), "")
    native_aliases: dict[str, list[str]] = {}
    if group.get("backend") == "browser":
        prefix = group["browser_directory"] + "/"
        for path, value in read_json(
            package / "catalog/native-relative-assets.json"
        ).items():
            if path.startswith(prefix) and value.startswith("input://"):
                rid = value[8:]
                if external.get(rid, {}).get("kind") == "font":
                    native_aliases.setdefault(rid, []).append(path.removeprefix(prefix))
                    references.setdefault(rid, [])
    if group.get("backend") == "scene":
        for rid in _SCENE_ENGINE_DEPENDENCIES.get(group["id"], ()):
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
        }
        for rid, fields in references.items()
    ]
