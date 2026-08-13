from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.aurora_main_image_planner import (
    PAGE_ROLES,
    _build_raw,
    _public_plan_payload,
)
from app.aurora_main_image_provider import AuroraMainImageProvider
from app.aurora_main_image_runtime import AuroraHarnessError, AuroraHarnessRunner
from app.provider import ProviderOutcome, ProviderRequest
from app.routes_v1 import _new_job_from_payload, runtime_status_response
from app.schemas_v1 import DomesticMainImageJobCreate
from app.xinghe_agent import FakeXingheGateway, PlannerRequest, SourceImage


def test_domestic_main_image_contract_is_exactly_six_page_input() -> None:
    payload = DomesticMainImageJobCreate.model_validate(
        {
            "type": "domestic_main_image",
            "input": {"product_asset_ids": ["asset_one", "asset_two"]},
            "configuration": {
                "product_name": "轻量随行杯",
                "category": "保温杯",
                "selling_points": ["杯盖防误开"],
            },
        }
    )
    job, roles = _new_job_from_payload("workspace_one", payload)
    assert job.expected_item_count == 6
    assert roles == [
        ("asset_one", "product_identity_authority", 0),
        ("asset_two", "product_identity_authority", 1),
    ]


def test_pasted_product_dossier_routes_service_away_from_product_page_leads() -> None:
    raw = _build_raw(
        "job_fact_routing",
        {
            "product_name": "蓝色赛车德训鞋",
            "category": "鞋子",
            "selling_points": [
                "一、基础商品信息",
                "商品全称：蓝色赛车德训鞋",
                "品牌：森果果",
                "发货与物流：免运费；平均16小时发货",
                "客服响应快（平均27秒回复）",
                "售后保障：7天无理由退货",
                "主打透气清爽",
                "主推配色：天蓝色+米白撞色",
                "翻毛皮浅蓝主体搭配米白流线型装饰",
                "日常休闲、通勤、出游、慢跑均可",
                "适配人群：学生党、小个子、宽胖脚/高脚背人群",
                "男女同款情侣板鞋",
            ],
        },
        ["product.jpg"],
    )
    product = raw["product"]
    assert product["verified_selling_points"][:6] == [
        "主打透气清爽",
        "适配人群：学生党、小个子、宽胖脚/高脚背人群",
        "主推配色：天蓝色+米白撞色",
        "翻毛皮浅蓝主体搭配米白流线型装饰",
        "日常休闲、通勤、出游、慢跑均可",
        "男女同款情侣板鞋",
    ]
    assert "一、基础商品信息" not in product["verified_selling_points"]
    assert product["verified_service_or_trust_facts"] == [
        "发货与物流：免运费；平均16小时发货",
        "客服响应快（平均27秒回复）",
        "售后保障：7天无理由退货",
    ]


def test_fake_gateway_returns_an_aurora_identity_contract() -> None:
    source = SourceImage(
        asset_id="asset_one",
        group_key="job_test",
        filename="product.png",
        content_type="image/png",
        sha256="0" * 64,
        payload=b"image-pixels",
    )
    result = asyncio.run(
        FakeXingheGateway().plan(
            PlannerRequest(
                workspace_id="workspace_one",
                job_id="job_test",
                group_key="job_test",
                sources=(source,),
                page_count=6,
                language="zh-CN",
                product_name="轻量随行杯",
                product_information=("杯盖防误开",),
                platform_code="TAOBAO_DOMESTIC_MAIN_IMAGE",
                size="1024x1024",
                idempotency_key="identity-test",
                planning_profile="aurora_identity",
            )
        )
    )
    assert result.error_code is None
    assert result.payload["request_id"] == "job_test"
    assert result.payload["evidence"][0]["evidence_id"] == "asset_one"
    assert result.payload["must_preserve"]


def test_compile_v013_builds_campaign_style_and_six_execution_contracts(
    tmp_path: Path,
) -> None:
    source_path = Path(__file__).resolve().parents[2] / "public" / "og.png"
    evidence_path = tmp_path / "product.png"
    evidence_path.write_bytes(source_path.read_bytes())
    raw = {
        "request_id": "job_compile",
        "profile01_semantics_read": False,
        "style_preferences": ["冷灰背景", "运动杂志感"],
        "product": {
            "name": "蓝色赛车德训鞋",
            "category": "男士运动鞋",
            "original_references": [str(evidence_path)],
            "verified_selling_points": ["复古赛车外观", "鞋底抓地纹路"],
            "verified_attributes": ["天蓝色与米白撞色"],
            "verified_scenes": ["城市通勤"],
            "verified_offers": [],
            "verified_service_or_trust_facts": ["48小时内发货"],
        },
    }
    identity = {
        "request_id": "job_compile",
        "product_form": "低帮系带运动鞋",
        "identity_summary": "天蓝色与米白撞色的低帮系带鞋，以原始商品图锁定身份。",
        "evidence": [
            {
                "evidence_id": "asset_one",
                "path": str(evidence_path),
                "view_tags": ["商品主视图"],
            }
        ],
        "must_preserve": ["鞋体轮廓", "蓝白配色", "鞋底比例"],
        "must_not_change": ["不得改变配色", "不得增加或删除部件"],
        "previous_generated_images_used": False,
        "profile01_semantics_read": False,
    }
    input_path = tmp_path / "input.json"
    identity_path = tmp_path / "identity.json"
    session_path = tmp_path / "session.json"
    output_path = tmp_path / "compiled.json"
    input_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
    runner = AuroraHarnessRunner()
    runner.run("start", tmp_path, {"input": input_path, "session": session_path})
    runner.run(
        "lock-identity",
        tmp_path,
        {"session": session_path, "identity": identity_path},
    )
    result = runner.run(
        "compile-v013",
        tmp_path,
        {"session": session_path, "output": output_path},
    )
    session = json.loads(session_path.read_text(encoding="utf-8"))
    public = _public_plan_payload(raw["product"], identity, session)

    assert result["status"] == "AWAITING_AUTHORIZATION"
    assert session["campaign_constitution"]["background_style_lock"]
    assert len(public["pages"]) == 6
    assert [page["page_role"] for page in public["pages"]] == list(PAGE_ROLES)
    assert all(page["main_selling_point"] for page in public["pages"])
    assert all(page["visual_proof"] for page in public["pages"])
    assert all(page["composition_and_subject"] for page in public["pages"])
    assert all(page["reading_path_and_type_hierarchy"] for page in public["pages"])
    assert all(page["non_repetition_reason"] for page in public["pages"])
    assert all(page["commercial_closure"] for page in public["pages"])
    assert all("发货" not in page["main_selling_point"] for page in public["pages"])


def test_real_runtime_exposes_registered_aurora_provider_when_enabled() -> None:
    runtime = runtime_status_response(
        environment="test",
        authentication_mode="development",
        task_runner="tengli",
        domestic_main_image_provider_enabled=True,
    )
    capability = runtime.capabilities.features["domestic_main_image"]
    assert capability.availability == "available"
    assert capability.execution == "provider"


def test_provider_completes_the_harness_controlled_six_page_loop(
    tmp_path: Path,
) -> None:
    job_id = "job_provider"
    workspace = tmp_path / job_id
    workspace.mkdir()
    evidence_path = workspace / "product.png"
    source_path = Path(__file__).resolve().parents[2] / "public" / "og.png"
    evidence_path.write_bytes(source_path.read_bytes())
    raw = {
        "request_id": job_id,
        "profile01_semantics_read": False,
        "product": {
            "name": "轻量随行杯",
            "category": "保温杯",
            "original_references": [str(evidence_path)],
            "verified_selling_points": ["杯盖防误开", "轻量便携"],
            "verified_attributes": ["可见杯盖结构"],
            "verified_scenes": ["城市通勤"],
            "verified_offers": [],
            "verified_service_or_trust_facts": ["48小时内发货"],
        },
    }
    identity = {
        "request_id": job_id,
        "product_form": "带盖随行杯",
        "identity_summary": "由原始图片锁定同一款带盖随行杯。",
        "evidence": [
            {
                "evidence_id": "asset_one",
                "path": str(evidence_path),
                "view_tags": ["商品主视图"],
            }
        ],
        "must_preserve": ["杯体轮廓", "杯盖结构", "颜色分区"],
        "must_not_change": ["不得增加部件", "不得改变杯体比例"],
        "previous_generated_images_used": False,
        "profile01_semantics_read": False,
    }
    input_path = workspace / "input.json"
    identity_path = workspace / "identity.json"
    session_path = workspace / "session.json"
    input_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
    runner = AuroraHarnessRunner()
    runner.run("start", workspace, {"input": input_path, "session": session_path})
    runner.run(
        "lock-identity",
        workspace,
        {"session": session_path, "identity": identity_path},
    )
    runner.run(
        "compile-v013",
        workspace,
        {"session": session_path, "output": workspace / "compiled.json"},
    )
    runner.run(
        "authorize",
        workspace,
        {"session": session_path, "approval-text": "确认六图规划并授权生成"},
    )

    class MemoryProvider(AuroraMainImageProvider):
        state = json.loads(session_path.read_text(encoding="utf-8"))

        def _load_authorized_context(self, request):  # type: ignore[no-untyped-def]
            del request
            return SimpleNamespace(
                ordinal=len(self.state["accepted_page_indexes"])
            ), dict(self.state)

        def _persist_session(self, job_id, harness_session):  # type: ignore[no-untyped-def]
            assert job_id == "job_provider"
            self.state = dict(harness_session)

    provider = MemoryProvider(
        session_factory=None,  # type: ignore[arg-type]
        gateway=FakeXingheGateway(),
        storage=None,  # type: ignore[arg-type]
        work_root=tmp_path,
    )
    for index in range(6):
        result = asyncio.run(
            provider.execute(
                ProviderRequest(
                    workspace_id="workspace_one",
                    job_id=job_id,
                    job_item_id=f"item_{index}",
                    attempt_id=f"attempt_{index}",
                    operation="domestic_main_image",
                    idempotency_key=f"provider-{index}",
                    configuration={},
                )
            )
        )
        assert result.outcome == ProviderOutcome.SUCCEEDED, result.error_message
        assert result.artifact is not None

    assert provider.state["accepted_page_indexes"] == [0, 1, 2, 3, 4, 5]
    assert provider.state["style_calibrated"] is True
    assert provider.state["search_baseline_calibrated"] is True
    assert provider.state["state"] == "AWAITING_USER_FINAL_REVIEW"


def test_harness_runner_rejects_unknown_commands(tmp_path: Path) -> None:
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run("python", tmp_path, {})
    assert captured.value.code == "HARNESS_COMMAND_NOT_ALLOWED"


def test_harness_runner_rejects_paths_outside_job_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run(
            "start",
            tmp_path,
            {"input": outside, "session": tmp_path / "session.json"},
        )
    assert captured.value.code == "HARNESS_PATH_OUTSIDE_WORKSPACE"
