"""Read a completed server planning job; never import a claimed model response.

These checks establish captured input/response lineage, not semantic correctness
or human approval. This module performs no provider call, even with flags off.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .motion_library import MOTION_SHA256, read_json, sha256
from .video_editing_contracts import SemanticPlan, Transcript
from .video_editing_first_groups import FIRST_MOTION_GROUPS, expand_group_plan
from .video_editing_materials import verify_material_cards
from .video_editing_native_plans import content_digest, source_assets
from .video_editing_planner import validate_plan
from .video_editing_planning_store import FILES, planning_root
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_template_materials import runtime_payload, validate_template_images
from .video_editing_transcript_store import read_transcript_artifact


@dataclass(frozen=True)
class VerifiedPlanning:
    task: EditingPlanningTaskRecord
    transcript: Transcript
    semantic: SemanticPlan
    lineage: dict[str, Any]


def _read(path: Path, root: Path, expected: dict | None = None) -> dict:
    path = path.resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or path.stat().st_size > 4_000_000
        or (
            expected is not None
            and (
                path.stat().st_size != expected["bytes"]
                or sha256(path) != expected["sha256"]
            )
        )
    ):
        raise ValueError("Captured planning artifact is missing or changed")
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("Captured planning artifact must be an object")
    return value


def verify_gateway_planning(
    session: Session,
    settings: Settings,
    workspace_id: str,
    owner_user_id: str,
    planning_task_id: str,
) -> VerifiedPlanning:
    row = session.get(EditingPlanningTaskRecord, planning_task_id)
    if (
        not row
        or row.workspace_id != workspace_id
        or row.owner_user_id != owner_user_id
    ):
        raise ApiError(404, "EDITING_PLANNING_NOT_FOUND", "未找到此用户的规划任务。")
    if (
        row.mode != "generate"
        or row.status != "completed"
        or not row.prepared_task_id
        or row.library_release != MOTION_SHA256
    ):
        raise ApiError(
            409,
            "EDITING_PLANNING_RESULT_REQUIRED",
            "仅已完成合同校验的服务器规划结果可以绑定原生配方。",
        )
    try:
        return _verify(session, settings, row)
    except (ValueError, KeyError, IndexError, TypeError, OSError) as error:
        raise ApiError(
            409,
            "EDITING_PLANNING_PROVENANCE_CHANGED",
            "规划输入、响应或来源摘要不一致，请核对原始记录。",
        ) from error


def _verify(
    session: Session, settings: Settings, row: EditingPlanningTaskRecord
) -> VerifiedPlanning:
    prepared = session.get(EditingPlanningTaskRecord, row.prepared_task_id)
    base = session.get(EditingTaskRecord, row.base_task_id)
    source = session.get(EditingSourceRecord, row.source_id)
    artifact = session.get(EditingArtifactRecord, row.base_transcript_artifact_id)
    scope = (row.workspace_id, row.owner_user_id, row.project_id, row.source_id)
    if (
        not prepared
        or prepared.mode != "prepare"
        or prepared.status != "prepared"
        or not base
        or base.status != "completed"
        or not source
        or not artifact
        or any(
            (v.workspace_id, v.owner_user_id, v.project_id, v.source_id) != scope
            for v in (prepared, base)
        )
        or (source.workspace_id, source.owner_user_id, source.project_id, source.id)
        != scope
        or any(
            getattr(prepared, key) != getattr(row, key)
            for key in (
                "base_task_id",
                "base_transcript_artifact_id",
                "base_transcript_sha256",
                "library_release",
                "model",
            )
        )
        or artifact.sha256 != row.base_transcript_sha256
        or row.snapshot["source_sha256"] != source.media_sha256
        or prepared.result["artifacts"] != row.snapshot["prepared_artifacts"]
        or prepared.snapshot
        != {
            k: v
            for k, v in row.snapshot.items()
            if k not in {"expected_request_sha256", "prepared_artifacts"}
        }
    ):
        raise ValueError("Planning source or prepared input identity changed")
    transcript = read_transcript_artifact(
        artifact, base, settings.video_editing_tasks_dir
    )
    if transcript.source_sha256 != source.media_sha256:
        raise ValueError("Planning transcript belongs to another source")
    parent_root = planning_root(settings, prepared.id)
    for captured_input in row.snapshot["prepared_artifacts"]:
        _read(Path(captured_input["path"]), parent_root, captured_input)
    root = planning_root(settings, row.id)
    manifest = row.result["artifacts"]
    captured = {a["role"]: a for a in manifest}
    if len(captured) != len(manifest) or not set(FILES) <= set(captured):
        raise ValueError("Planning capture is incomplete or has duplicate roles")
    files, data = {}, {}
    for role, name in FILES.items():
        record = captured[role]
        file = Path(record["path"]).resolve()
        if role not in {"transcript", "lineage"} and file != root / "provider" / name:
            raise ValueError("Planning capture is not in its stable provider directory")
        data[role] = _read(file, root, record)
        files[role] = record["sha256"]
    intent_path = root / "provider/semantic-submit-intent.json"
    intent = _read(intent_path, root)
    request_sha = hashlib.sha256(
        json.dumps(data["request"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if (
        any(
            value != request_sha
            for value in (
                row.result["request_sha256"],
                row.snapshot["expected_request_sha256"],
                prepared.result["request_sha256"],
                intent["request_sha256"],
                data["request_evidence"]["request_sha256"],
                data["response"]["request_sha256"],
                data["receipt"]["request_sha256"],
            )
        )
        or data["request"]["model"] != row.model
        or data["receipt"]["response_sha256"] != files["response"]
        or data["receipt"]["plan_sha256"] != files["semantic_plan"]
        or data["receipt"]["validation"] != "contract_only"
        or data["response"].get("provider_envelope_valid") is not True
        or not row.snapshot.get("gateway")
        or intent["gateway"] != row.snapshot["gateway"]
        or data["response"]["gateway"] != row.snapshot["gateway"]
        or data["request_evidence"]["catalog_group_count"] != 132
        or files["transcript"] != artifact.sha256
        or data["lineage"]["base_task_id"] != base.id
        or data["lineage"]["base_transcript_artifact_id"] != artifact.id
        or data["lineage"]["base_transcript_sha256"] != artifact.sha256
        or data["lineage"]["source_sha256"] != source.media_sha256
    ):
        raise ValueError("Captured input, response and validation hashes disagree")
    payload = json.loads(data["request"]["messages"][1]["content"])
    runtime = row.snapshot.get("planning_runtime")
    template = row.snapshot.get("overlay_template")
    compact = bool(template and template["id"] in FIRST_MOTION_GROUPS)
    selected = (
        {slot["group_id"] for slot in template["slots"]}
        if template and compact
        else None
    )
    if runtime is not None and (
        payload.get("template_runtime") != runtime_payload(runtime)
        or {
            group["id"]: {
                "sample": group["website_runtime"],
                "dependencies": group.get("known_original_dependencies", []),
            }
            for group in payload["full_library"]
            if selected is None or group["id"] in selected
        }
        != {
            key: value
            for key, value in runtime["groups"].items()
            if selected is None or key in selected
        }
    ):
        raise ValueError("Captured runtime evidence differs from the prepared snapshot")
    groups = read_json(settings.video_editing_library_dir / "catalog/groups.json")
    if (
        len(payload["full_library"]) != 132
        or {g["id"] for g in payload["full_library"]}
        != {g["id"] for g in groups["groups"]}
        or (
            payload.get("word_clock")
            != [
                [i, t.text, t.start_ms, t.end_ms]
                for i, t in enumerate(transcript.tokens)
            ]
            if compact
            else payload["transcript"]["tokens"]
            != [{"id": t.id, "text": t.text} for t in transcript.tokens]
        )
        or payload["project_library_choices"] != row.snapshot["choice_snapshot"]
        or payload["available_project_materials"] != row.snapshot["asset_cards"]
        or payload.get("overlay_template") != row.snapshot.get("overlay_template")
    ):
        raise ValueError("Captured full-library request does not match scoped inputs")
    content = data["response"]["content"]
    if template and template["id"] in FIRST_MOTION_GROUPS:
        semantic = expand_group_plan(
            content,
            transcript,
            settings.video_editing_library_dir,
            template,
            row.snapshot["asset_cards"],
            row.snapshot["choice_snapshot"],
            runtime,
        )
    else:
        semantic = SemanticPlan.model_validate_json(content)
    value = semantic.model_dump(mode="json")
    if (
        value != data["semantic_plan"]
        or value != row.result["semantic"]
        or content_digest(value) != row.result["semantic_content_sha256"]
    ):
        raise ValueError("Native adoption would change the captured semantic result")
    validate_plan(
        semantic,
        transcript,
        settings.video_editing_library_dir,
        {a["id"] for a in row.snapshot["asset_cards"]},
        row.snapshot["choice_snapshot"],
        (runtime or {}).get("unavailable_template_groups"),
    )
    validate_template_images(semantic, runtime, row.snapshot["asset_cards"])
    return VerifiedPlanning(
        row,
        transcript,
        semantic,
        {
            "version": "tengli.planning-provenance/1",
            "planning_task_id": row.id,
            "prepared_task_id": row.prepared_task_id,
            "base_task_id": base.id,
            "base_transcript_artifact_id": artifact.id,
            "base_transcript_sha256": artifact.sha256,
            "source_sha256": source.media_sha256,
            "library_release": row.library_release,
            "choice_snapshot_sha256": row.snapshot["choice_snapshot"]["sha256"],
            "requested_model": row.model,
            "response_model": data["response"].get("model"),
            "gateway": row.snapshot["gateway"],
            "request_sha256": request_sha,
            "artifact_sha256": files,
            "intent_sha256": sha256(intent_path),
            "semantic_content_sha256": content_digest(value),
            "semantic_review": "unreviewed",
        },
    )


def verify_render_provenance(
    session: Session, settings: Settings, native: dict[str, Any]
) -> str | None:
    if native["origin"] == "operator_candidate":
        if native["recipes"]["planning_origin"] != "operator_candidate":
            raise ValueError("Operator plan cannot declare a model origin")
        return None
    if native["origin"] != "tengli_gateway":
        raise ValueError("Unknown planning origin")
    captured = native.get("planning_provenance")
    if not captured:
        raise ValueError("Model native plan needs a captured server planning job")
    verified = verify_gateway_planning(
        session,
        settings,
        native["workspace_id"],
        native["owner_user_id"],
        captured["planning_task_id"],
    )
    source = session.get(EditingSourceRecord, verified.task.source_id)
    if not source:
        raise ValueError("Planning source disappeared during verification")
    assets = source_assets(source) | verify_material_cards(
        session,
        settings,
        source,
        verified.task.snapshot["asset_cards"],
        verify_bytes=False,
    )
    if (
        verified.lineage != captured
        or verified.task.project_id != native["project_id"]
        or verified.task.source_id != native["source_id"]
        or verified.task.base_task_id != native["base_task_id"]
        or verified.task.base_transcript_sha256 != native["base_transcript_sha256"]
        or verified.task.snapshot["choice_snapshot"] != native["choice_snapshot"]
        or verified.semantic.model_dump(mode="json") != native["semantic"]
        or native["recipes"]["planning_origin"] != "tengli_gateway"
        or native["asset_files"] != assets
    ):
        raise ValueError("Frozen native plan does not match its captured planning job")
    return hashlib.sha256(verified.semantic.model_dump_json().encode()).hexdigest()
