"""Resume an already validated master or proxy within one editing task."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .motion_library import read_json, sha256
from .video_editing_audio_verification import AUDIO_VALIDATION_VERSION
from .video_editing_native_frame_clock import CLOCK_RECEIPTS

_VERSION = "tengli.editing-delivery/1"
_PATHS = {
    "final": "outputs/episode.mp4",
    "staged_final": "outputs/episode.mp4",
    "preview": "outputs/preview.mp4",
    "receipt": "validation.json",
    "preview_receipt": "preview-validation.json",
    "transcript": "transcript.json",
    "caption_anchors": "caption-anchors.json",
    "caption_receipt": "caption-segmentation.json",
    "caption_layout": "caption-adapter-layout.json",
    "source_receipt": "source-receipt.json",
    "semantic_plan": "semantic-plan.json",
    "compile_receipt": "compile-diagnostics.json",
    "plan_lineage": "native-plan-lineage.json",
    "audio_receipt": "audio-validation.json",
    "layout_receipt": "layout/adapter-review.json",
    "alignment_receipt": "alignment-receipt.json",
}
_BASE_RECEIPTS = {
    "receipt",
    "transcript",
    "caption_anchors",
    "caption_receipt",
    "caption_layout",
}


def normalize_attempt_paths(value: Any, root: Path) -> Any:
    roots = (str(root), root.as_posix())
    prefixes = (roots[0] + "\\", roots[1] + "/")
    if isinstance(value, dict):
        return {
            normalize_attempt_paths(key, root): normalize_attempt_paths(item, root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_attempt_paths(item, root) for item in value]
    if isinstance(value, str):
        if value in roots:
            return "instance:///"
        for prefix in prefixes:
            if value.startswith(prefix):
                return "instance:///" + value[len(prefix) :].replace("\\", "/")
    return value


def compiled_digest(root: Path, request_hash: str) -> str:
    """Bind the original engine inputs while allowing a new attempt directory."""
    inputs: dict[str, Any] = {
        name: normalize_attempt_paths(read_json(root / name), root)
        for name in (
            "episode.json",
            "selection.json",
            "bindings.json",
            "transcript.json",
        )
    }
    inputs["audio_validation_version"] = AUDIO_VALIDATION_VERSION
    for name in (
        "audio-plan.json",
        "layout-intent.json",
        "inset-layout-intent.json",
        *CLOCK_RECEIPTS,
    ):
        if (root / name).is_file():
            inputs[name] = normalize_attempt_paths(read_json(root / name), root)
    return hashlib.sha256(
        json.dumps([request_hash, inputs], ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class DeliveryFile:
    path: Path
    sha256: str
    bytes: int

    @property
    def mime(self) -> str:
        return {".mp4": "video/mp4", ".wav": "audio/wav"}.get(
            self.path.suffix, "application/json"
        )


def delivery_file(path: Path) -> DeliveryFile:
    return DeliveryFile(path, sha256(path), path.stat().st_size)


def checkpoint_for(
    task_root: Path, plan_sha256: str, files: dict[str, DeliveryFile]
) -> dict[str, Any]:
    return {
        "version": _VERSION,
        "plan_sha256": plan_sha256,
        "files": {
            role: {
                "path": file.path.relative_to(task_root).as_posix(),
                "sha256": file.sha256,
                "bytes": file.bytes,
            }
            for role, file in files.items()
        },
    }


def _restore_file(
    role: str, entry: dict, task_root: Path, guard: Callable[[], None]
) -> DeliveryFile:
    attempt, path = entry["path"].split("/", 1)
    if not re.fullmatch(r"[0-9a-f]{8}", attempt) or path != _PATHS[role]:
        raise ValueError("Delivery checkpoint has an invalid artifact path")
    expected = task_root / attempt / path
    if expected.resolve() != expected or expected.stat().st_size != entry["bytes"]:
        raise ValueError("Delivery checkpoint artifact changed")
    guard()
    file = delivery_file(expected)
    if file.sha256 != entry["sha256"] or file.bytes != entry["bytes"]:
        raise ValueError("Delivery checkpoint artifact changed")
    return file


def restore_delivery(
    checkpoint: Any,
    task_root: Path,
    plan_sha256: str,
    source_sha256: str,
    final_role: str,
    required_receipts: set[str],
    guard: Callable[[], None],
) -> tuple[dict[str, DeliveryFile], dict[str, dict]] | None:
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("version") != _VERSION
        or checkpoint.get("plan_sha256") != plan_sha256
    ):
        return None
    try:
        recorded = checkpoint["files"]
        roles = set(recorded)
        preview_roles = {"preview", "preview_receipt"}
        if (
            not (required_receipts | _BASE_RECEIPTS | {final_role}) <= roles
            or ({"final", "staged_final"} & roles) != {final_role}
            or not roles <= _PATHS.keys()
            or (preview_roles & roles and final_role != "staged_final")
        ):
            return None
        files = {
            role: _restore_file(role, entry, task_root, guard)
            for role, entry in recorded.items()
            if role not in preview_roles
        }
        master = read_json(files["receipt"].path)
        if (
            master["sha256"] != files[final_role].sha256
            or master["native_source_sha256"] != source_sha256
            or master["decoded"] is not True
            or (
                master.get("native_mix_validation") == "passed"
                and "audio_receipt" not in roles
            )
        ):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    validation = {final_role: master}
    if preview_roles <= roles:
        try:
            proxy_files = {
                role: _restore_file(role, recorded[role], task_root, guard)
                for role in preview_roles
            }
            preview = read_json(proxy_files["preview_receipt"].path)
            if (
                preview["sha256"] == proxy_files["preview"].sha256
                and preview["native_render_sha256"] == master["sha256"]
                and preview["duration_ms"] == master["duration_ms"]
                and preview["decoded"] is True
            ):
                files.update(proxy_files)
                validation["preview"] = preview
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    return files, validation
