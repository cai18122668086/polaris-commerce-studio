"""Fill a freshly authored native recipe; never fall back to historical content.

Recipes are trusted adapter/operator data, NOT model output. They must provide
the current design and all non-anchor native parameters. This module does not
invent a universal renderer or silently replace an unsupported original group.
"""

import copy
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from .motion_parameter_contracts import input_contract
from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_media_clocks import compile_media_clocks
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


def _set(value: dict, path: str, assigned: Any) -> None:
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


def compile_native_job(
    package: Path,
    root: Path,
    beat: SemanticBeat,
    transcript: Transcript,
    recipe: dict[str, Any],
    asset_files: dict[str, dict[str, Any]],
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
    contract = input_contract(package, group)
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
    if group["backend"] == "hypit":
        # Compound caps/items and alternate picture-parallel profiles require
        # their original authoring protocol, not JSON-to-DSL interpolation.
        raise ValueError("Hypit requires an explicit original authoring recipe")
    config = copy.deepcopy(recipe["config"])
    if not _same_shape(read_json(package / group["input_template"]), config):
        raise ValueError(
            "This recipe changes native field/array topology; "
            "an explicit variant authoring contract is required"
        )
    decisions = recipe.get("parameter_decisions", {})
    placeholders = recipe.get("placeholders", [])
    if len(placeholders) != len(set(placeholders)):
        raise ValueError("Duplicate recipe placeholder")
    native = word_bindings(beat, transcript, contract, set(asset_files))
    media_clocks, clock_receipts = compile_media_clocks(
        package,
        group,
        contract,
        native,
        recipe.get("media_clocks", []),
        asset_files,
        transcript,
    )
    native["media_clocks"] = clock_receipts
    assignments = (
        {row["path"]: row["text"] for row in native["text"]}
        | {row["path"]: row["value"] for row in native["events"]}
        | media_clocks
    )
    omitted = recipe.get("empty_text", {})
    for path, reason in omitted.items():
        if (
            path not in contract["text_paths"]
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
    for rid, declared_path in recipe.get("dependency_bindings", {}).items():
        identity = dependency_rows.get(rid, {})
        source = Path(declared_path).resolve()
        if (
            identity.get("kind") not in {"font", "model"}
            or not source.is_file()
            or sha256(source) != identity.get("sha256")
        ):
            raise ValueError(
                "Original font/model dependency bytes do not match: " + rid
            )
        resources[rid] = str(source)
    for row in native["media"]:
        asset = asset_files[row["asset_id"]]
        source = Path(asset["path"]).resolve()
        if not source.is_file() or sha256(source) != asset["sha256"]:
            raise ValueError("Current project material is missing or changed")
        rid = "tengli-" + asset["sha256"][:24]
        resources[rid] = str(source)
        assignments[row["path"]] = "input://" + rid
    for field in contract["fields"]:
        path, category = field["path"], field["category"]
        value = _get(config, path)
        if category in {"text", "event", "resource", "optional_media"}:
            if path not in assignments or path not in placeholders or value is not None:
                raise ValueError(
                    "Fresh native content/event/media needs an empty bound slot: "
                    + path
                )
        elif category == "native_dependency":
            if not decisions.get(path.split("/")[1]) and not decisions.get(path):
                raise ValueError("Record the native font/model choice: " + path)
            if not isinstance(value, str) or value[8:] not in resources:
                raise ValueError(
                    "Exact original font/model dependency is not bound: " + path
                )
        elif category == "numeric_content_requires_grounding":
            raise ValueError(
                "Native numeric content needs a fact-grounded recipe: " + path
            )
        elif category == "output_owned_by_compiler":
            _set(config, path, str(root / "renders/component.mp4"))
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
                _set(config, path, math.ceil(duration * contract["native_fps"]))
            elif key in {"duration", "duration_seconds"} and not path.startswith(
                "/media/"
            ):
                _set(config, path, duration)
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
        _set(config, path, value)
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
    atomic_json(root / "bindings.json", {"resources": resources, "tools": {}})
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
            "schema_validation": "passed",
            "native_execution": "not_performed",
            "semantic_review": "unreviewed",
            "visual_review": "unreviewed",
            "hearing_review": "unreviewed",
        },
    )
    return job
