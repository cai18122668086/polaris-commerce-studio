"""Real coordinator and native compilation, with an explicit synthetic supplier."""

from copy import deepcopy
from dataclasses import replace

import pytest

from app.domestic_detail import authoring
from app.xinghe_agent import (
    _complete_aurora_module_structure,
    _planner_response_format,
)
from tests.test_api import WORKSPACE_ID, dispatch_pending, upload_asset
from tests.test_domestic_detail_execution import _create_detail_job, _gateway
from tests.test_domestic_detail_planner_contract import request


@pytest.mark.parametrize("count", [1, 3, 5])
def test_authored_payload_count_survives_adapter(count):
    raw = {"proof": {"minimum_visual_payload": count}}
    assert (
        _complete_aurora_module_structure(raw)["proof"]["minimum_visual_payload"]
        == count
    )
    assert raw == {"proof": {"minimum_visual_payload": count}}


def test_story_wire_locks_count_ids_and_excludes_detailed_modules():
    value = request(authoring_stage="story")
    schema = _planner_response_format(value)["json_schema"]["schema"]
    modules = schema["properties"]["modules"]
    assert modules["minItems"] == modules["maxItems"] == 8
    assert [m["properties"]["id"] for m in modules["prefixItems"]] == [
        {"const": f"M{i:02d}"} for i in range(1, 9)
    ]
    assert "proof" not in modules["prefixItems"][0]["properties"]
    assert schema["properties"]["operating_strategy"]["required"]


def test_actual_staged_coordinator_reaches_native_approval(client):
    source = upload_asset(client, filename="bounded-product.png")
    job = _create_detail_job(
        client, source["id"], market_region="domestic", auto_start_after_plan=False
    )
    dispatch_pending(client)
    planned = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}").json()
    assert planned["status"] == "awaiting_confirmation", (
        planned.get("error_code"),
        planned.get("error_message"),
        planned.get("plan", {}).get("payload", {}).get("validation_errors"),
    )
    calls = _gateway(client).planner_calls
    assert [c.authoring_stage for c in calls] == [
        "",
        "story",
        "pair",
        "pair",
        "pair",
        "pair",
    ]
    assert [c.authoring_target_ids for c in calls[2:]] == [
        ("M01", "M02"),
        ("M03", "M04"),
        ("M05", "M06"),
        ("M07", "M08"),
    ]
    assert all(not c.sources for c in calls[2:])
    assert len(calls[1].system_prompt) < 40000
    assert planned["plan"]["payload"]["native_approval"]["document_sha256"]
    assert not _gateway(client).image_calls


def test_pair_does_not_change_story_or_accept_wrong_zone_count(client):
    source = upload_asset(client, filename="bounded-schema.png")
    _create_detail_job(
        client, source["id"], market_region="domestic", auto_start_after_plan=False
    )
    dispatch_pending(client)
    calls = _gateway(client).planner_calls
    pair = next(c for c in calls if c.authoring_stage == "pair")
    schema = _planner_response_format(pair)["json_schema"]["schema"]
    first = schema["properties"]["modules"]["prefixItems"][0]
    assert first["properties"]["lead_conclusion"] == {
        "const": pair.authoring_context["modules"][0]["lead_conclusion"]
    }
    assert schema["properties"]["modules"]["minItems"] == 2
    assert schema["properties"]["modules"]["maxItems"] == 2
    assert authoring.errors_for({"modules": []}, _planner_response_format(pair))
    from app.domestic_detail.mock_intake import mock_plan_with_intake
    from app.xinghe_agent import _fake_plan

    payload = authoring.fake_phase(
        mock_plan_with_intake(_fake_plan(pair), pair.detail_intake), pair
    )
    payload["modules"][0]["structure"] = {
        **payload["modules"][0]["structure"],
        "structure_family": "FULL_BLEED_HERO",
        "zone_briefs": ["one", "two", "three"],
    }
    assert any(
        "structure" in e["path"]
        for e in authoring.errors_for(payload, _planner_response_format(pair))
    )


def test_native_depth_is_not_overwritten():
    from app.domestic_detail.contracts import normalize_native_plan_for_harness

    depth = {
        "selection_policy": "authored",
        "primary_claim_ids": ["F01"],
        "claim_depth": [
            {
                "claim_id": "F01",
                "module_jobs": [{"module_id": "M03", "job": "DEDICATED_EXPRESSION"}],
            }
        ],
    }
    normalized = normalize_native_plan_for_harness(
        {"modules": [], "selling_point_depth_contract": deepcopy(depth)}
    )
    assert normalized["selling_point_depth_contract"] == depth


@pytest.mark.parametrize("failure", ["invalid", "unknown", "deadline"])
def test_bounded_failure_stops_without_new_task_or_images(client, monkeypatch, failure):
    gateway = _gateway(client)
    original = gateway.plan

    async def controlled(value):
        result = await original(value)
        if value.authoring_stage == "story":
            if failure == "unknown":
                return replace(
                    result,
                    payload=None,
                    error_code="PROVIDER_TRANSPORT_FAILED",
                    error_message="unknown",
                    http_status=None,
                )
            if failure == "invalid":
                payload = deepcopy(result.payload)
                payload["modules"].append(deepcopy(payload["modules"][-1]))
                return replace(result, payload=payload)
        return result

    monkeypatch.setattr(gateway, "plan", controlled)
    if failure == "deadline":
        monkeypatch.setattr(authoring, "PLANNING_SECONDS", 0.0)
    source = upload_asset(client, filename="bounded-stop.png")
    job = _create_detail_job(
        client, source["id"], market_region="domestic", auto_start_after_plan=False
    )
    dispatch_pending(client)
    result = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}").json()
    assert result["status"] == "failed"
    assert not any(c.authoring_stage == "pair" for c in gateway.planner_calls)
    assert (
        len(gateway.planner_calls)
        == {"invalid": 3, "unknown": 2, "deadline": 1}[failure]
    )
    assert not gateway.image_calls


def test_resolved_conflict_wire_requires_identity_even_with_historical_conflict():
    from app.domestic_detail.intake import intake_prompt, intake_response_schema

    settings = {
        "product_name": "参考图女鞋",
        "selling_points": ["尖头轮廓"],
        "brandless_confirmation": "用户确认仅作来源水印，测试图不添加品牌",
    }
    resolution = {
        "resolutions": [
            {
                "conflict_id": "C01",
                "retained_fact_ids": ["F01"],
                "rejected_fact_ids": ["O02"],
            }
        ]
    }
    wire = request(
        planning_profile="aurora_domestic_intake",
        intake_settings=settings,
        intake_resolution=resolution,
    )
    schema = _planner_response_format(wire)["json_schema"]["schema"]
    assert {"identity", "identity_observations"}.issubset(schema["required"])
    assert schema["properties"]["identity"]["type"] == "object"
    assert "allOf" not in schema  # provider-compatible root stays intact
    unresolved = intake_response_schema(wire_settings=settings)
    assert "identity" not in unresolved["required"]
    prompt = intake_prompt(settings=settings, sources=[], resolution=resolution)
    assert "Do not stop at the old conflict again" in prompt
    assert "material conflict MUST stop" not in prompt
    before = intake_prompt(settings=settings, sources=[])
    assert "material conflict MUST stop" in before
