from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.aurora_main_image_planner import _build_pages
from app.aurora_main_image_runtime import AuroraHarnessError, AuroraHarnessRunner
from app.routes_v1 import _new_job_from_payload, runtime_status_response
from app.schemas_v1 import DomesticMainImageJobCreate


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
    assert payload.configuration.language == "zh-CN"
    assert payload.input.product_asset_ids == ["asset_one", "asset_two"]

    job, roles = _new_job_from_payload("workspace_one", payload)
    assert job.expected_item_count == 6
    assert roles == [
        ("asset_one", "product_identity_authority", 0),
        ("asset_two", "product_identity_authority", 1),
    ]


def test_mock_planner_turns_facts_into_distinct_visual_decisions() -> None:
    settings: dict[str, object] = {
        "product_name": "蓝色赛车训练鞋",
        "category": "男士运动鞋",
        "selling_points": ["复古赛车外观", "鞋底抓地纹路"],
        "scenes": ["城市通勤"],
        "service_or_trust_facts": ["48 小时内发货"],
        "style_preferences": ["冷灰背景"],
    }

    pages = _build_pages(settings, ["asset_one"])

    assert len(pages) == 6
    assert [page["page_role"] for page in pages] == list(
        (
            "SEARCH_MAIN_IMAGE_LISTING_COVER",
            "CAROUSEL_IDENTITY_HERO",
            "CAROUSEL_CORE_FEATURE_PROOF",
            "CAROUSEL_SCENE_OR_OPERATION",
            "CAROUSEL_DETAIL_OR_TRUST",
            "CAROUSEL_OFFER_OR_SPEC_CLOSURE",
        )
    )
    assert len({str(page["headline"]) for page in pages}) == 6
    assert not any(page["headline"] in settings["selling_points"] for page in pages)
    assert all(page["composition"] for page in pages)
    assert all(page["copy_direction"] for page in pages)
    assert pages[3]["evidence"] == ["城市通勤"]
    assert pages[5]["evidence"] == ["48 小时内发货"]


def test_mock_planner_does_not_invent_missing_scene_or_offer() -> None:
    pages = _build_pages(
        {
            "product_name": "便携水杯",
            "category": "杯壶",
            "selling_points": ["杯盖防误开"],
        },
        ["asset_one"],
    )

    assert "未提供已核实场景" in str(pages[3]["objective"])
    assert "不制造促销角标" in str(pages[5]["composition"])


def test_mock_planner_classifies_a_pasted_product_brief() -> None:
    pages = _build_pages(
        {
            "product_name": "蓝色赛车德训鞋",
            "category": "鞋子",
            "selling_points": [
                "蓝色赛车德训鞋完整产品信息",
                "一、基础商品信息",
                "1. 商品全称：蓝色德训鞋男女款",
                "2. 品牌：示例品牌",
                "5. 发货与物流：免运费；平均16小时发货",
                "主打透气清爽",
                "日常休闲、通勤、出游、慢跑均可",
                "天蓝色+米白撞色",
            ],
        },
        ["asset_one"],
    )

    assert pages[0]["evidence"][-1] == "主打透气清爽"
    assert pages[3]["evidence"] == ["日常休闲、通勤、出游、慢跑均可"]
    assert pages[4]["evidence"] == ["天蓝色+米白撞色"]
    assert pages[5]["evidence"] == ["发货与物流：免运费；平均16小时发货"]
    serialized = json.dumps(pages, ensure_ascii=False)
    assert "一、基础商品信息" not in serialized
    assert "商品全称" not in serialized


def test_harness_runner_rejects_unknown_commands(tmp_path: Path) -> None:
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run("python", tmp_path, {})
    assert captured.value.code == "HARNESS_COMMAND_NOT_ALLOWED"


def test_real_runtime_stays_fail_closed_until_provider_adapter_is_registered() -> None:
    runtime = runtime_status_response(
        environment="test",
        authentication_mode="development",
        task_runner="tengli",
        domestic_main_image_provider_enabled=True,
    )
    capability = runtime.capabilities.features["domestic_main_image"]
    assert capability.availability == "unavailable"
    assert capability.reason_code == "REAL_PROVIDER_NOT_REGISTERED"


def test_harness_runner_rejects_paths_outside_job_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    with pytest.raises(AuroraHarnessError) as captured:
        AuroraHarnessRunner().run(
            "start",
            tmp_path,
            {"input": outside, "session": tmp_path / "session.json"},
        )
    assert captured.value.code == "HARNESS_PATH_OUTSIDE_WORKSPACE"


def test_harness_start_runs_through_bundled_entrypoint(tmp_path: Path) -> None:
    raw = {
        "request_id": "job_test",
        "profile01_semantics_read": False,
        "product": {
            "name": "轻量随行杯",
            "category": "保温杯",
            "original_references": ["asset_one"],
            "verified_selling_points": ["杯盖防误开"],
        },
    }
    input_path = tmp_path / "input.json"
    session_path = tmp_path / "session.json"
    input_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    result = AuroraHarnessRunner().run(
        "start",
        tmp_path,
        {"input": input_path, "session": session_path},
    )
    assert result["status"] == "AWAITING_IDENTITY"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["request_id"] == "job_test"
