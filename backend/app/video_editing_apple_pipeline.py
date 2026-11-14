"""Apple suite adapter for the existing durable planning and delivery queues.

This engine owns its bundle identity. It never registers fabricated groups in
the preserved 132-group motion catalog and never makes per-frame model calls.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .motion_library import atomic_json, read_json, sha256
from .video_assistance_provider import (
    VideoAssistanceProvider,
    planner_configured,
    planner_endpoint,
)
from .video_editing_contracts import Transcript
from .video_editing_delivery_checkpoint import delivery_file
from .video_editing_materials import verify_material_cards
from .video_editing_pipeline import EditingFailure, decode_av, probe, run
from .video_editing_preview import build_preview
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_transcript_store import read_transcript_artifact

TEMPLATE_ID = "apple-minimal-v1"
ENGINE = "apple-minimal-suite"
TEMPLATE_NAME = "科技发布 · 苹果极简"
FONT_IDS = {
    "support": "font-fbecfacdfac33982",
    "main": "font-62383707c086a32f",
    "caption": "font-9c62ceb174d7529a",
    "caption_bold": "font-62383707c086a32f",
}


def suite_engine(snapshot: dict) -> bool:
    return snapshot.get("engine") in {ENGINE, "bihuo-full-suite"}


def suite_fonts(settings: Settings) -> dict[str, str]:
    root = settings.video_editing_library_dir.resolve()
    assets = {
        row["id"]: row for row in read_json(root / "asset-manifest.json")["assets"]
    }
    result = {}
    for role, asset_id in FONT_IDS.items():
        row = assets[asset_id]
        path = (root / row["path"]).resolve()
        if (
            row.get("kind") != "font"
            or not row["sha256"].startswith(asset_id.removeprefix("font-"))
            or not path.is_relative_to(root)
            or not path.is_file()
            or sha256(path) != row["sha256"]
        ):
            raise ApiError(
                409,
                "EDITING_APPLE_FONT_CHANGED",
                "模板字体暂不可用，请恢复字体文件后重试。",
            )
        result[role] = str(path)
    return result


def suite_bundle(settings: Settings, template_id: str | None = None) -> dict:
    if template_id is not None and template_id != TEMPLATE_ID:
        from .bihuo_suite.registry import bundle_identity as bihuo_bundle_identity

        return bihuo_bundle_identity(template_id)
    from .video_editing_apple_contracts import bundle_identity

    identity = bundle_identity()
    if identity.get("engine") != ENGINE or not identity.get("sha256"):
        raise ValueError("Invalid Apple engine bundle identity")
    fonts = suite_fonts(settings)
    return {
        **identity,
        "font_sha256": {role: sha256(Path(path)) for role, path in fonts.items()},
    }


def assert_bundle(snapshot: dict, settings: Settings) -> None:
    current = (
        suite_bundle(settings, snapshot["template_id"])
        if snapshot.get("engine") == "bihuo-full-suite"
        else suite_bundle(settings)
    )
    if current != snapshot["engine_bundle"]:
        raise ApiError(
            409,
            "EDITING_APPLE_BUNDLE_CHANGED",
            "模板版本已变化，请重新检查素材后继续。",
        )


def suite_card(settings: Settings, workspace_id: str) -> dict | None:
    try:
        bundle = suite_bundle(settings)
        if (
            not Path(__file__)
            .with_name("apple_minimal")
            .joinpath("render.py")
            .is_file()
        ):
            return None
    except (ImportError, OSError, ValueError, KeyError, ApiError):
        return None
    return {
        "id": TEMPLATE_ID,
        "version": bundle["version"],
        "engine": ENGINE,
        "name": TEMPLATE_NAME,
        "category": "科技发布",
        "featured": True,
        "description": "统一的渐白标题、人物让位、资料窗口、要点与结论编排。",
        "visual_features": ["蓝白极简", "双层标题", "人物小窗与素材接力"],
        "material_requirements": [
            "无烧字的9:16竖屏口播",
            "可选：有名称或说明的图片、录屏",
        ],
        "material_mode": "speech",
        "group_ids": [],
        "sampled_group_count": 0,
        "pending_original_group_ids": [],
        "status": "unverified",
        "status_label": "成套模板 · 本期效果待预览",
        "business_review": "pending",
        "example": None,
        "signature_group_ids": [],
        "style_preview": None,
        "capabilities": [
            "title",
            "subtitle",
            "name_card",
            "cover",
            "reference_script",
            "music",
        ],
    }


def _request_digest(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def material_placement(plan: dict, transcript: Transcript, cards: list[dict]) -> dict:
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    assets = {card["id"]: card for card in cards}
    assignments = []
    used = set()
    for item in plan.get("materials", []):
        asset = assets[item["asset_id"]]
        first, last = (
            positions[item["first_token_id"]],
            positions[item["last_token_id"]],
        )
        show = transcript.tokens[positions[item["show_at_token_id"]]]
        used.add(item["asset_id"])
        assignments.append(
            {
                "asset_id": item["asset_id"],
                "sha256": asset["sha256"],
                "label": asset["viewed_identity"],
                "description": asset["semantic_use"],
                "first_token_id": item["first_token_id"],
                "last_token_id": item["last_token_id"],
                "spoken_text": "".join(
                    token.text for token in transcript.tokens[first : last + 1]
                ),
                "start_ms": transcript.tokens[first].start_ms,
                "end_ms": transcript.tokens[last].end_ms,
                "show_at_token_id": show.id,
                "show_at_ms": show.end_ms
                if item.get("edge") == "end"
                else show.start_ms,
                "edge": item.get("edge", "start"),
            }
        )
    return {
        "version": "tengli.apple-material-placement/1",
        "planning": "single full-script request before rendering",
        "assignments": assignments,
        "unused_asset_ids": sorted(
            card["id"]
            for card in cards
            if card["kind"] in {"image", "video"} and card["id"] not in used
        ),
    }


def plan_suite(
    root: Path,
    attempt: Path,
    snapshot: dict,
    transcript: Transcript,
    model: str,
    mode: str,
    settings: Settings,
    provider: Any,
    guard: Callable[..., None],
    prepared_request: dict | None = None,
) -> tuple[str, dict]:
    from .video_editing_apple_contracts import build_request, verify_plan

    assert_bundle(snapshot, settings)
    profile = None
    if snapshot.get("engine") == "bihuo-full-suite":
        from .bihuo_suite.registry import definition

        meta = definition(snapshot["template_id"])
        profile = {
            **meta,
            "engine": snapshot["engine"],
            "version": snapshot["engine_bundle"]["version"],
            "flow": meta["description"],
        }
    request_options = {"template_profile": profile} if profile is not None else {}
    body, evidence = build_request(
        transcript,
        model,
        snapshot["asset_cards"],
        snapshot.get("creative_options"),
        **request_options,
    )
    if prepared_request is not None:
        # Reuse the exact prepared body instead of silently changing model input.
        if body != prepared_request:
            raise ApiError(
                409, "EDITING_PLAN_INPUT_CHANGED", "规划输入已变化，请重新检查素材。"
            )
        body = prepared_request
    evidence = {**evidence, "request_sha256": _request_digest(body)}
    result = {**evidence, "text_status": transcript.text_status}
    if mode == "prepare":
        atomic_json(attempt / "semantic-request.json", body)
        atomic_json(attempt / "semantic-request-evidence.json", evidence)
        return "prepared", result
    if evidence["request_sha256"] != snapshot["expected_request_sha256"]:
        raise ApiError(409, "EDITING_PLAN_INPUT_CHANGED", "规划输入与检查记录不一致。")
    guard("planning")
    folder = root / "provider"
    folder.mkdir(parents=True, exist_ok=True)
    intent, response_path = (
        folder / "semantic-submit-intent.json",
        folder / "semantic-response.json",
    )
    if intent.exists():
        if read_json(intent).get("request_sha256") != evidence["request_sha256"]:
            raise ApiError(
                409, "EDITING_PLAN_INPUT_CHANGED", "已提交请求与本次输入不一致。"
            )
        if not response_path.is_file():
            raise ApiError(
                409, "EDITING_PLAN_ALREADY_SUBMITTED", "模型结果待确认，请勿重复提交。"
            )
        response = read_json(response_path)
    else:
        if not settings.video_editing_planning_enabled or (
            isinstance(provider, VideoAssistanceProvider)
            and not planner_configured(settings)
        ):
            raise ApiError(503, "EDITING_PLANNING_DISABLED", "自动剪辑暂不可用。")
        guard()
        try:
            with intent.open("x", encoding="utf8") as stream:
                json.dump(
                    {**evidence, "gateway": planner_endpoint(settings)},
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
        except FileExistsError:
            raise ApiError(
                409, "EDITING_PLAN_ALREADY_SUBMITTED", "本次规划已提交，请等待结果。"
            ) from None
        atomic_json(folder / "semantic-request.json", body)
        guard()
        data = provider.request(
            "planner",
            "POST",
            "/v1/chat/completions",
            json=body,
            read_timeout=min(210, settings.video_editing_lease_seconds - 5),
        )
        choices = data.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else None
        )
        content = message.get("content") if isinstance(message, dict) else None
        response = {
            "request_sha256": evidence["request_sha256"],
            "content": content if isinstance(content, str) else None,
            "provider_envelope_valid": isinstance(content, str),
            "model": data.get("model"),
            "usage": data.get("usage"),
            "provider_id": data.get("id"),
            "gateway": planner_endpoint(settings),
        }
        atomic_json(response_path, response)
    if response.get("request_sha256") != evidence["request_sha256"]:
        raise ApiError(
            409, "EDITING_PLAN_RESPONSE_MISMATCH", "已保存响应与本次规划不一致。"
        )
    guard()
    plan = verify_plan(
        json.loads(response["content"]),
        transcript,
        snapshot["asset_cards"],
        require_semantic_captions=True,
        allow_mixed_body=snapshot.get("engine") == "bihuo-full-suite",
    )
    path = folder / "suite-plan.json"
    atomic_json(path, plan)
    atomic_json(
        folder / "material-placement.json",
        material_placement(plan, transcript, snapshot["asset_cards"]),
    )
    atomic_json(folder / "semantic-request-evidence.json", evidence)
    atomic_json(
        folder / "semantic-validated.json",
        {
            "engine": snapshot.get("engine", ENGINE),
            "engine_bundle": snapshot["engine_bundle"],
            "request_sha256": evidence["request_sha256"],
            "response_sha256": sha256(response_path),
            "plan_sha256": sha256(path),
            "validation": "contract_only",
            "semantic_review": "unreviewed",
            "visual_review": "unreviewed",
        },
    )
    result.update(
        suite_plan=plan,
        suite_plan_sha256=sha256(path),
        native_render_state="not_compiled",
    )
    return "completed", result


def verified_suite(
    session: Session,
    settings: Settings,
    plan_id: str,
    source: EditingSourceRecord,
) -> tuple[EditingPlanningTaskRecord, Transcript, dict[str, dict]]:
    row = session.get(EditingPlanningTaskRecord, plan_id)
    if (
        not row
        or not suite_engine(row.snapshot)
        or row.status != "completed"
        or row.mode != "generate"
        or not row.prepared_task_id
        or (row.workspace_id, row.owner_user_id, row.project_id, row.source_id)
        != (source.workspace_id, source.owner_user_id, source.project_id, source.id)
    ):
        raise ApiError(
            404, "EDITING_SUITE_PLAN_NOT_FOUND", "未找到此口播的完整模板规划。"
        )
    assert_bundle(row.snapshot, settings)
    base = session.get(EditingTaskRecord, row.base_task_id)
    record = session.get(EditingArtifactRecord, row.base_transcript_artifact_id)
    if (
        not base
        or not record
        or record.sha256 != row.base_transcript_sha256
        or base.source_id != source.id
    ):
        raise ApiError(409, "EDITING_PLAN_SOURCE_CHANGED", "口播或规划输入已变化。")
    transcript = read_transcript_artifact(
        record, base, settings.video_editing_tasks_dir
    )
    if (
        transcript.source_sha256 != source.media_sha256
        or sha256(Path(source.media_path)) != source.media_sha256
    ):
        raise ApiError(409, "EDITING_SOURCE_CHANGED", "原片已变化，请重新选择视频。")
    root = (
        settings.video_editing_tasks_dir / "_planning" / row.id / "provider"
    ).resolve()
    path = root / "suite-plan.json"
    receipt = read_json(root / "semantic-validated.json")
    if (
        not path.is_file()
        or sha256(path) != row.result.get("suite_plan_sha256")
        or sha256(path) != receipt.get("plan_sha256")
        or receipt.get("request_sha256") != row.result.get("request_sha256")
        or receipt.get("engine_bundle") != row.snapshot["engine_bundle"]
    ):
        raise ApiError(
            409, "EDITING_PLANNING_PROVENANCE_CHANGED", "无法核对已保存的模板规划。"
        )
    if sha256(root / "semantic-response.json") != receipt.get("response_sha256"):
        raise ApiError(
            409, "EDITING_PLANNING_PROVENANCE_CHANGED", "已保存规划响应发生变化。"
        )
    from .video_editing_apple_contracts import verify_plan

    plan = verify_plan(
        read_json(path),
        transcript,
        row.snapshot["asset_cards"],
        allow_mixed_body=row.snapshot.get("engine") == "bihuo-full-suite",
    )
    if plan != row.result.get("suite_plan"):
        raise ApiError(
            409, "EDITING_PLANNING_PROVENANCE_CHANGED", "规划内容与校验记录不一致。"
        )
    assets = verify_material_cards(
        session, settings, source, row.snapshot["asset_cards"], verify_bytes=True
    )
    return row, transcript, assets


def render_suite(
    root: Path,
    snapshot: dict,
    settings: Settings,
    session: Session,
    guard: Callable[..., None],
    stage: Callable[..., None],
) -> tuple[dict, dict]:
    from .video_editing_apple_contracts import compile_render_input

    source = session.get(EditingSourceRecord, snapshot["source_id"])
    if source is None:
        raise EditingFailure("EDITING_SOURCE_CHANGED")
    row, transcript, assets = verified_suite(
        session, settings, snapshot["options"]["suite_plan_id"], source
    )
    plan, frozen = row.result["suite_plan"], dict(row.snapshot)
    source_path, source_sha = source.media_path, source.media_sha256
    original_source_path = Path(source_path)
    # The source and planning rows above are now frozen in local values. Do not
    # hold a database transaction through preparation, inference and encoding.
    session.rollback()
    compiler = None
    selected_fonts = None
    render_module = "app.apple_minimal.render"
    if frozen.get("engine") == "bihuo-full-suite":
        from .bihuo_suite.registry import compile_request, definition, fonts
        from .bihuo_suite.source import prepare as prepare_suite_source

        template_id = frozen["template_id"]
        selected_fonts = fonts(template_id)
        render_module = "app.bihuo_suite.render"
        creative_options = dict(frozen.get("creative_options") or {})
        stage("preparing_source", engine=frozen["engine"])
        source_path = str(
            prepare_suite_source(
                Path(source_path), transcript.duration_ms / 1000, root, settings, guard
            )
        )
        if definition(template_id).get("requires_foreground"):
            from .bihuo_suite.foreground import prepare as prepare_foreground

            stage("preparing_foreground", engine=frozen["engine"])
            creative_options["foreground_cache"] = prepare_foreground(
                Path(source_path), transcript.duration_ms / 1000, settings, guard
            )

        def compiler(resolved: dict, **kwargs: Any) -> dict:
            kwargs.pop("fonts", None)
            kwargs.pop("music", None)
            return compile_request(template_id, resolved, **kwargs)

    else:
        selected_fonts = suite_fonts(settings)
        creative_options = dict(frozen.get("creative_options") or {})

    config = compile_render_input(
        plan,
        transcript,
        assets,
        source_path,
        selected_fonts,
        creative_options=creative_options,
        music=frozen.get("music", "template"),
        ffmpeg=settings.video_editing_ffmpeg,
        recipe_compiler=compiler,
    )
    session.rollback()
    config_path = root / "suite-input.json"
    atomic_json(config_path, config)
    atomic_json(root / "suite-plan.json", plan)
    atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
    stage(
        "rendering",
        engine=frozen.get("engine", ENGINE),
        engine_bundle=frozen["engine_bundle"],
    )
    output = root / "suite-render"
    run(
        [
            settings.video_editing_python,
            "-B",
            "-X",
            "utf8",
            "-m",
            render_module,
            "--input",
            str(config_path),
            "--output",
            str(output),
        ],
        root,
        settings,
        guard,
        "apple_suite_render",
    )
    final = output / "final.mp4"
    receipt = read_json(output / "render-receipt.json")
    if not final.is_file() or receipt.get("final_sha256") != sha256(final):
        raise EditingFailure("EDITING_APPLE_OUTPUT_CHANGED")
    assert_bundle(frozen, settings)
    if sha256(original_source_path) != source_sha:
        raise EditingFailure("EDITING_SOURCE_CHANGED")
    stage("validating")
    decode_av(final, root, settings, guard, "decode_apple_suite")
    info = probe(final, settings)
    video = next(
        stream for stream in info["streams"] if stream["codec_type"] == "video"
    )
    if (video.get("width"), video.get("height")) != (1080, 1920) or video.get(
        "codec_name"
    ) != "h264":
        raise EditingFailure("EDITING_APPLE_OUTPUT_INVALID")
    duration = round(float(video["duration"]) * 1000)
    if abs(duration - transcript.duration_ms) > 80:
        raise EditingFailure("EDITING_APPLE_CLOCK_CHANGED")
    validation = {
        "engine": frozen.get("engine", ENGINE),
        "engine_bundle": frozen["engine_bundle"],
        "input_sha256": sha256(config_path),
        "plan_sha256": sha256(root / "suite-plan.json"),
        "source_sha256": source_sha,
        "sha256": sha256(final),
        "duration_ms": duration,
        "width": video["width"],
        "height": video["height"],
        "decoded": True,
        "visual_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    (root / "outputs").mkdir(exist_ok=True)
    stage("building_preview")
    preview, preview_receipt = build_preview(final, root, validation, settings, guard)
    atomic_json(root / "suite-validation.json", validation)
    files = {
        "staged_final": delivery_file(final),
        "preview": delivery_file(preview),
        "preview_receipt": delivery_file(root / "preview-validation.json"),
        "receipt": delivery_file(root / "suite-validation.json"),
        "suite_plan": delivery_file(root / "suite-plan.json"),
        "render_receipt": delivery_file(output / "render-receipt.json"),
        "transcript": delivery_file(root / "transcript.json"),
    }
    if frozen.get("creative_options", {}).get("cover", "auto") != "none":
        poster = root / "outputs/poster.jpg"
        run(
            [
                settings.video_editing_ffmpeg,
                "-v",
                "error",
                "-ss",
                str(min(1.6, duration / 2000)),
                "-i",
                str(final),
                "-frames:v",
                "1",
                "-vf",
                "scale=540:960",
                "-q:v",
                "2",
                "-y",
                str(poster),
            ],
            root,
            settings,
            guard,
            "apple_cover",
        )
        files["poster"] = delivery_file(poster)
    return files, {
        "staged_final": validation,
        "preview": preview_receipt,
        "transcript": {"duration_ms": transcript.duration_ms},
    }
