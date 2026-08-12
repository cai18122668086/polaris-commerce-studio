from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.aurora_detail_planner import AuroraPlanningContext, _mock_bundle
from app.aurora_detail_provider import XingheAuroraRequestCompiler
from app.aurora_detail_runtime import (
    AURORA_DETAIL_SKILL_ID,
    AURORA_DETAIL_VERSION,
    AuroraDetailHarnessAdapter,
    AuroraDetailRuntimeError,
    GenerationProviderCapabilities,
    assert_provider_receipt,
    compile_generation_envelope,
)
from app.config import default_skill_root
from app.skill_runtime import SkillManifestRegistry
from app.xinghe_agent import FakeXingheGateway, SourceImage
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _compiled_request(tmp_path: Path):  # type: ignore[no-untyped-def]
    product = tmp_path / "product.png"
    reference = tmp_path / "reference.png"
    product.write_bytes(b"stable-product-reference")
    reference.write_bytes(b"stable-style-reference")
    sources = (
        SourceImage(
            "product",
            "primary-product",
            product.name,
            "image/png",
            _sha256(product.read_bytes()),
            product.read_bytes(),
            "product_reference",
        ),
        SourceImage(
            "reference",
            "primary-product",
            reference.name,
            "image/png",
            _sha256(reference.read_bytes()),
            reference.read_bytes(),
            "style_reference",
        ),
    )
    context = AuroraPlanningContext(
        workspace_id="ws_test",
        job_id="job_test",
        product_name="测试商品",
        category="家居",
        target_buyer="家庭用户",
        primary_scenario="居家使用",
        platform_code="tmall",
        product_facts=("真实材质", "便于收纳"),
        output_preferences="真实克制",
        sources=sources,
        stable_paths={"product": str(product), "reference": str(reference)},
        existing_session=None,
        revision=1,
    )
    bundle = _mock_bundle(context)
    adapter = AuroraDetailHarnessAdapter(tmp_path / "runtime")
    result = adapter.start("job_test", bundle["raw_input"])
    result = adapter.lock_identity("job_test", result.session, bundle["identity"])
    result = adapter.compile_plan("job_test", result.session, bundle["plan"])
    result = adapter.authorize(
        "job_test",
        result.session,
        approval_text="确认 storyboard、模块数量和比例",
        approved_module_count=3,
        approved_aspect_ratio="3:4",
    )
    result, request = adapter.generate_next("job_test", result.session)
    return result.session, request


def test_frozen_aurora_skill_manifest_and_version_are_valid() -> None:
    manifest = SkillManifestRegistry.bundled().get(AURORA_DETAIL_SKILL_ID)
    assert manifest.content_hash == (
        "81a42fb61b99a793313168f455cb06006d7c08f963bc6c16d394fa826493db72"
    )
    assert len(manifest.files) == 35
    assert (
        default_skill_root(AURORA_DETAIL_SKILL_ID)
        .joinpath("VERSION")
        .read_text(encoding="utf-8")
        .strip()
        == AURORA_DETAIL_VERSION
    )


def test_generate_next_is_locked_to_exact_prompt_and_ordered_references(
    tmp_path: Path,
) -> None:
    session, request = _compiled_request(tmp_path)
    capabilities = GenerationProviderCapabilities(
        ordered_references=True,
        primary_edit_image=True,
        fixed_model_version=True,
        idempotency=True,
        request_recovery=True,
    )
    envelope = compile_generation_envelope(
        request,
        session,
        capabilities=capabilities,
        model="image-model",
        model_version="2026-08-01",
        endpoint="https://provider.invalid/v1/images/edits",
        parameters={"quality": "high"},
        idempotency_key="job_test:M01:cycle-1:attempt-1",
    )
    assert envelope.prompt == request["prompt"]
    assert envelope.prompt_sha256 == _sha256(request["prompt"].encode("utf-8"))
    assert envelope.reference_images == tuple(request["reference_images"])
    assert_provider_receipt(
        envelope,
        prompt_sha256=envelope.prompt_sha256,
        ordered_reference_sha256=envelope.reference_sha256,
        edit_target_sha256=envelope.edit_target_sha256,
        model=envelope.model,
        model_version=envelope.model_version,
        endpoint=envelope.endpoint,
        parameters=envelope.parameters,
    )
    prepared = XingheAuroraRequestCompiler(
        FakeXingheGateway(), model_version="gpt-image-2@2026-08-01"
    ).prepare(
        request,
        session,
        workspace_id="ws_test",
        job_id="job_test",
        job_item_id="item_test",
        attempt_id="attempt_test",
        page_number=1,
        idempotency_key="job_test:M01:cycle-1:attempt-1",
    )
    assert prepared.request.prompt == request["prompt"]
    assert tuple(source.filename for source in prepared.request.sources) == tuple(
        Path(path).name for path in request["reference_images"]
    )
    assert prepared.request.idempotency_key == envelope.idempotency_key


def test_provider_capability_mismatch_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    session, request = _compiled_request(tmp_path)
    with pytest.raises(
        AuroraDetailRuntimeError,
        match="Provider lacks ordered references",
    ):
        compile_generation_envelope(
            request,
            session,
            capabilities=GenerationProviderCapabilities(
                ordered_references=False,
                primary_edit_image=True,
                fixed_model_version=True,
                idempotency=True,
                request_recovery=True,
            ),
            model="image-model",
            model_version="2026-08-01",
            endpoint="https://provider.invalid/v1/images/edits",
            parameters={},
            idempotency_key="locked-request",
        )


def test_zero_cost_api_flow_requires_explicit_dynamic_plan_authorization(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="aurora-product.png")
    created = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "display_name": "Aurora v0.7.0 zero-cost planning",
            "input": {
                "product_groups": [
                    {
                        "group_key": "primary-product",
                        "asset_ids": [source["id"]],
                    }
                ],
                "reference_asset_ids": [],
            },
            "configuration": {
                "workflow_version": "aurora_v0.7.0",
                "product_name": "收纳盒",
                "category": "家居",
                "target_buyer": "小户型家庭",
                "primary_scenario": "厨房收纳",
                "product_facts": ["透明材质", "可叠放"],
                "selling_points": ["便于查看内容物"],
                "output_preferences": "真实克制",
                "platform_code": "tmall",
                "market_region": "domestic",
                "language": "zh-CN",
                "auto_start_after_plan": False,
                "size": "1200x1600",
            },
        },
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    assert dispatch_pending(client) == 1

    response = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/aurora-detail"
    )
    assert response.status_code == 200, response.text
    planned = response.json()
    assert planned["state"] == "AWAITING_PLAN_APPROVAL"
    assert planned["output_decision"]["module_count"] == len(
        planned["storyboard"]
    )
    candidates = planned["output_decision"]["module_count_candidates"]
    assert len({item["count"] for item in candidates}) >= 2

    authorized = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/aurora-detail/authorize",
        headers=idem(),
        json={
            "expected_revision": planned["revision"],
            "approval_text": "确认 storyboard、模块数量和单屏比例",
            "approved_module_count": planned["output_decision"]["module_count"],
            "approved_aspect_ratio": planned["output_decision"]["aspect_ratio"],
        },
    )
    assert authorized.status_code == 202, authorized.text
    assert authorized.json()["state"] == "AUTHORIZED"

    stale = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/aurora-detail/authorize",
        headers=idem(),
        json={
            "expected_revision": planned["revision"],
            "approval_text": "stale approval",
            "approved_module_count": planned["output_decision"]["module_count"],
            "approved_aspect_ratio": planned["output_decision"]["aspect_ratio"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "AURORA_SESSION_REVISION_CONFLICT"

    planner = client.app.state.task_runner.coordinator.detail_planner
    gateway = planner.international.gateway
    image_calls_before = len(gateway.image_calls)
    assert dispatch_pending(client) == 1
    assert len(gateway.image_calls) == image_calls_before
