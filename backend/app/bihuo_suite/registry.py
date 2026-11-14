"""Installed executable suites, their style grammar, and portable font resources."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ENGINE = "bihuo-full-suite"
ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def definitions() -> dict[str, dict]:
    return {row["id"]: row for row in _read(CATALOG)["templates"]}


def is_template(template_id: str | None) -> bool:
    return template_id in definitions()


def definition(template_id: str) -> dict:
    try:
        return definitions()[template_id]
    except KeyError:
        raise ValueError("Unknown full-suite template") from None


def _inside(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError("Installed suite resource is missing or outside its bundle")
    return p


@lru_cache(maxsize=64)
def _installed(template_id: str, manifest_bytes: bytes) -> tuple[dict, Path]:
    meta = definition(template_id)
    folder = ROOT / "templates" / meta["bundle"]
    manifest = json.loads(manifest_bytes)
    if manifest["schema"] != "tengli.bihuo-runtime-bundle/1":
        raise ValueError("Unknown suite bundle schema")
    for relative, digest in manifest["files"].items():
        path = _inside(folder, relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Installed suite resource changed: " + relative)
    if manifest["runtime"] not in manifest["files"]:
        raise ValueError("Suite runtime is not in the immutable file manifest")
    for relative in manifest["fonts"].values():
        if relative not in manifest["files"]:
            raise ValueError("Suite font is not in the immutable file manifest")
    return manifest, folder


def installed(template_id: str) -> tuple[dict, Path]:
    meta = definition(template_id)
    path = ROOT / "templates" / meta["bundle"] / "bundle.json"
    return _installed(template_id, path.read_bytes())


def available(template_id: str) -> bool:
    try:
        if not definition(template_id).get("enabled", True):
            return False
        installed(template_id)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def fonts(template_id: str) -> dict[str, str]:
    manifest, folder = installed(template_id)
    return {
        role: str(_inside(folder, relative))
        for role, relative in manifest["fonts"].items()
    }


def bundle_identity(template_id: str) -> dict[str, str]:
    from ..video_editing_apple_contracts import bundle_identity as planning_identity

    meta = definition(template_id)
    manifest, folder = installed(template_id)
    identity = {
        "template": meta,
        "manifest": manifest,
        "planner": planning_identity(),
        "host_runtime": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path(__file__),
                ROOT / "render.py",
                ROOT / "foreground.py",
                ROOT / "source.py",
            ]
        },
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "engine": ENGINE,
        "template_id": template_id,
        "version": manifest["version"],
        "sha256": digest,
    }


def runtime(template_id: str) -> Any:
    manifest, folder = installed(template_id)
    path = _inside(folder, manifest["runtime"])
    revision = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()[:16]
    key = (
        "app.bihuo_suite.templates."
        + definition(template_id)["bundle"]
        + "_"
        + revision
    )
    # A package search path permits the bundle's explicitly shipped relative imports.
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            key, path, submodule_search_locations=[str(folder)]
        )
        if spec is None or spec.loader is None:
            raise ValueError("Suite runtime could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return sys.modules[key]


def compile_request(template_id: str, resolved: dict, **kwargs: Any) -> dict:
    module = runtime(template_id)
    config = module.compile_request(resolved, fonts=fonts(template_id), **kwargs)
    if not isinstance(config, dict):
        raise ValueError("Suite compiler must return executable JSON parameters")
    return {"template_id": template_id, "config": config}


def creative_options(template_id: str, value: dict) -> dict:
    result = dict(value)
    supported = definition(template_id).get("capabilities", [])
    for field in ["title", "subtitle"]:
        if field not in supported:
            result[field] = ""
    if "name_card" not in supported or not (result.get("name_card") or {}).get(
        "enabled", True
    ):
        result["name_card"] = {"enabled": False, "name": "", "description": ""}
    return result


def cards() -> list[dict]:
    result = []
    for template_id, meta in definitions().items():
        if not available(template_id):
            continue
        identity = bundle_identity(template_id)
        result.append(
            {
                "id": template_id,
                "version": identity["version"],
                "engine": ENGINE,
                "name": meta["name"],
                "category": meta["category"],
                "featured": False,
                "description": meta["description"],
                "visual_features": meta["visual_features"],
                "material_requirements": [
                    "无烧字的9:16竖屏口播",
                    "配图可选，按实际内容调整布局"
                    if "images" in meta.get("capabilities", [])
                    else "按口播组织文字画面，无需配图",
                    *(
                        ["人物名片可选，不填写则不显示"]
                        if "name_card" in meta.get("capabilities", [])
                        else []
                    ),
                ],
                "material_mode": "speech",
                "group_ids": [],
                "sampled_group_count": 0,
                "pending_original_group_ids": [],
                "status": "sample_backed",
                "status_label": "成套模板",
                "business_review": "pending",
                "example": None,
                "signature_group_ids": [],
                "style_preview": None,
                "capabilities": meta.get(
                    "capabilities",
                    [
                        "title",
                        "subtitle",
                        "name_card",
                        "cover",
                        "reference_script",
                        "music",
                    ],
                ),
            }
        )
    return result
