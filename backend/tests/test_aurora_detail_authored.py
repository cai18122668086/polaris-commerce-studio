# ruff: noqa: E501
"""精致版 detail authored from the aurora detail Skill v2.3.0 in one plan."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app import aurora_detail_authored, detail_fast_runtime, refined_detail
from app.provider import ProviderArtifact
from app.skill_runtime import SkillManifestRegistry
from app.xinghe_agent import load_planner_system_prompt
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset
from tests.test_domestic_detail_execution import _gateway

BASE = f"/api/v1/workspaces/{WORKSPACE_ID}"


def create(client, *, count=8, auto_start=False, size=None):
    source = upload_asset(client)
    response = client.post(
        BASE + "/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "display_name": "精致测试",
            "input": {"product_groups": [{"group_key": "primary", "asset_ids": [source["id"]]}]},
            "configuration": {
                "detail_skill": "refined",
                "product_name": "离线测试商品",
                "platform_code": "tmall",
                "market_region": "domestic",
                "page_count": count,
                "selling_points": ["合成测试输入"],
                "auto_start_after_plan": auto_start,
                **({"size": size} if size else {}),
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def planned(client, **kwargs):
    job = create(client, **kwargs)
    dispatch_pending(client)
    job = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert job["status"] == "awaiting_confirmation", job
    return job


def confirmation(job):
    return {
        "expected_revision": job["plan"]["revision"],
        "approval_text": "我已审阅完整方案，确认按此生成。",
        "approval_document_sha256": job["plan"]["payload"]["refined_approval"]["document_sha256"],
    }


def synthetic_edit(gateway, monkeypatch):
    gateway.provider_name = "synthetic"
    original_edit = gateway.edit

    async def edit(request):
        result = await original_edit(request)
        output = BytesIO()
        Image.new("RGB", (1440, 1920), (request.page_number, 60, 90)).save(output, "PNG")
        data = output.getvalue()
        return replace(
            result,
            artifact=ProviderArtifact(
                payload=data, filename=f"synthetic-{request.page_number}.png",
                content_type="image/png", width=1440, height=1920,
                sha256=hashlib.sha256(data).hexdigest(),
            ),
        )

    async def skip_delay(_delay):
        return None

    monkeypatch.setattr(gateway, "edit", edit)
    monkeypatch.setattr("app.execution.asyncio.sleep", skip_delay)


def test_source_is_the_owner_skill_and_planner_reads_its_references_verbatim():
    source = Path(__file__).resolve().parents[1] / "skill_sources" / aurora_detail_authored.SKILL_ID
    SkillManifestRegistry.bundled().verify_source(aurora_detail_authored.SKILL_ID, source)
    assert (source / "VERSION").read_text(encoding="utf-8").strip() == "2.3.0"
    prompt = load_planner_system_prompt(source, aurora_detail_authored.SKILL_ID)
    for relative in aurora_detail_authored.PROTOCOL_FILES:
        assert (source / relative).read_text(encoding="utf-8") in prompt
    # The harness runbook is not sent: one-pass authoring restates its gates.
    assert "python scripts/harness.py" not in prompt


@pytest.mark.parametrize("count", [1, 3, 8, 12])
def test_new_refined_jobs_plan_once_with_the_aurora_contract(client, count):
    job = planned(client, count=count)
    gateway = _gateway(client)
    assert job["configuration"]["domestic_detail_pipeline"] == aurora_detail_authored.PIPELINE_VERSION
    assert detail_fast_runtime.contract(job["configuration"]) is aurora_detail_authored
    assert len(gateway.planner_calls) == 1
    assert gateway.planner_calls[0].planning_profile == aurora_detail_authored.PROFILE
    assert not gateway.image_calls
    payload = job["plan"]["payload"]
    assert len(payload["pages"]) == count
    aurora_detail_authored.validate_payload(payload, count)
    assert payload["detail_fast"]["version"] == aurora_detail_authored.PIPELINE_VERSION
    approval = payload["refined_approval"]
    assert approval["document_sha256"] == aurora_detail_authored.approval_hash(payload)
    for hidden in ("image_prompt", "page_prompt", "aurora", "2.3"):
        assert hidden not in approval["document_markdown"]
    for page in payload["pages"]:
        prompt = page["image_prompt"]
        assert prompt.startswith("vertical 3:4 e-commerce detail page image")
        assert page["page_prompt"] in prompt
        assert len(prompt) < 3000


def test_confirmed_plan_generates_every_screen_once_and_completes(client, monkeypatch):
    gateway = _gateway(client)
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    synthetic_edit(gateway, monkeypatch)
    job = planned(client)
    pages = job["plan"]["payload"]["pages"]
    response = client.post(f"{BASE}/jobs/{job['id']}/plan/confirm", headers=idem(), json=confirmation(job))
    assert response.status_code == 202, response.text
    dispatch_pending(client)
    current = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert current["status"] == "completed", current
    assert len(gateway.image_calls) == 8
    assert sorted(call.prompt for call in gateway.image_calls) == sorted(page["image_prompt"] for page in pages)


def test_auto_start_runs_without_a_confirmation(client, monkeypatch):
    gateway = _gateway(client)
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    synthetic_edit(gateway, monkeypatch)
    job = create(client, count=4, auto_start=True)
    dispatch_pending(client)
    current = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert current["status"] == "completed", current
    assert len(gateway.image_calls) == 4


@pytest.mark.parametrize("size", ["750x1000", "990x1320", "1242x1656"])
def test_screens_are_generated_hd_and_delivered_at_the_chosen_platform_size(
    client, monkeypatch, size
):
    gateway = _gateway(client)
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    synthetic_edit(gateway, monkeypatch)
    job = create(client, count=2, auto_start=True, size=size)
    dispatch_pending(client)
    current = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert current["status"] == "completed", current
    assert {call.size for call in gateway.image_calls} == {"1440x1920"}
    width, height = (int(value) for value in size.split("x"))
    outputs = [a for a in current["assets"] if a["is_deliverable"] and a["direction"] == "output"]
    assert len(outputs) == 2
    for asset in outputs:
        assert (asset["validation"]["actual_width"], asset["validation"]["actual_height"]) == (width, height)


def test_sizes_outside_the_3_4_platform_set_are_refused(client):
    source = upload_asset(client)
    response = client.post(
        BASE + "/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "display_name": "精致测试",
            "input": {"product_groups": [{"group_key": "primary", "asset_ids": [source["id"]]}]},
            "configuration": {
                "detail_skill": "refined", "product_name": "离线测试商品", "platform_code": "tmall",
                "market_region": "domestic", "page_count": 2, "selling_points": ["合成测试输入"],
                "size": "1600x1600",
            },
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "DETAIL_SIZE_UNSUPPORTED"


def test_extra_selling_point_slips_are_tidied_not_fatal():
    from types import SimpleNamespace

    request = SimpleNamespace(product_name="离线测试商品", page_count=2, sources=())
    strategy = aurora_detail_authored.fake_strategy(request)
    strategy["analysis"]["extra_selling_points"] = [
        {"point": "0% 谷物", "source": "包装原图2", "reason": "包装正面印有 0% 谷物", "pages": [2], "note": "x"}
    ]
    normalized = aurora_detail_authored.normalize_strategy(strategy)
    assert normalized["analysis"]["extra_selling_points"] == [
        {"point": "0% 谷物", "source": "包装原图2", "basis": "包装正面印有 0% 谷物", "pages": [2]}
    ]


def test_an_empty_screen_plan_is_replanned_once(client, monkeypatch):
    gateway = _gateway(client)
    original_plan = gateway.plan
    calls = {"count": 0}

    async def plan(request):
        result = await original_plan(request)
        calls["count"] += 1
        if calls["count"] == 1:
            payload = dict(result.payload)
            payload["plan"] = {**payload["plan"], "screens": []}
            return replace(result, payload=payload)
        return result

    monkeypatch.setattr(gateway, "plan", plan)
    job = planned(client, count=3)
    assert calls["count"] == 2
    assert len(job["plan"]["payload"]["pages"]) == 3


def test_a_second_empty_screen_plan_fails_the_job(client, monkeypatch):
    gateway = _gateway(client)
    original_plan = gateway.plan
    calls = {"count": 0}

    async def plan(request):
        result = await original_plan(request)
        calls["count"] += 1
        payload = dict(result.payload)
        payload["plan"] = {**payload["plan"], "screens": []}
        return replace(result, payload=payload)

    monkeypatch.setattr(gateway, "plan", plan)
    job = create(client, count=3)
    dispatch_pending(client)
    job = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert calls["count"] == 2
    assert job["status"] == "failed" and job["error_code"] == "AURORA_DETAIL_PLAN_INVALID"


def test_missing_screens_are_redone_only_after_the_user_confirms_them(client, monkeypatch):
    from app.provider import ProviderOutcome

    gateway = _gateway(client)
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    synthetic_edit(gateway, monkeypatch)
    edit = gateway.edit
    calls = []

    async def unknown_once(request):
        calls.append(request.page_number)
        result = await edit(request)
        if request.page_number == 2 and calls.count(2) == 1:
            return replace(result, outcome=ProviderOutcome.OUTCOME_UNKNOWN, artifact=None,
                           error_code="PROVIDER_OUTCOME_UNKNOWN")
        return result

    monkeypatch.setattr(gateway, "edit", unknown_once)
    job = create(client, count=3, auto_start=True)
    dispatch_pending(client)
    source = client.get(f"{BASE}/jobs/{job['id']}").json()
    assert source["status"] == "partial", source
    # An ordinary retry still refuses a page whose outcome is unknown.
    blocked = client.post(f"{BASE}/jobs/{job['id']}/retry", headers=idem(), json={"scope": "failed"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "PROVIDER_OUTCOME_UNKNOWN"
    missing = client.get(f"{BASE}/jobs/{job['id']}/detail/missing-pages").json()
    assert missing["delivered_pages"] == [0, 2]
    assert [(p["page_index"], p["reason"]) for p in missing["missing_pages"]] == [(1, "结果未确认")]
    assert missing["credits_per_page"] == 15 and missing["max_credits"] == 15
    wrong = client.post(f"{BASE}/jobs/{job['id']}/retry", headers=idem(),
                        json={"scope": "failed", "confirm_missing_pages": [0, 1]})
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "MISSING_PAGES_CHANGED"
    redo = client.post(f"{BASE}/jobs/{job['id']}/retry", headers=idem(),
                       json={"scope": "failed", "confirm_missing_pages": [1]})
    assert redo.status_code == 201, redo.text
    child = redo.json()
    assert child["cost"]["estimated_credits"] == 15
    dispatch_pending(client)
    final = client.get(f"{BASE}/jobs/{child['id']}").json()
    assert final["status"] == "completed", final
    assert sorted(calls) == [1, 2, 2, 3]
    again = client.post(f"{BASE}/jobs/{job['id']}/retry", headers=idem(),
                        json={"scope": "failed", "confirm_missing_pages": [1]})
    assert again.status_code == 409


def test_flag_off_keeps_the_historical_xinghe_pipeline(client, monkeypatch):
    monkeypatch.setenv("POLARIS_DETAIL_AURORA_AUTHORED", "false")
    job = create(client)
    assert job["configuration"]["domestic_detail_pipeline"] == refined_detail.PIPELINE_VERSION


def test_primary_source_falls_back_to_a_product_reference():
    request = type("R", (), {"page_count": 2, "product_name": "x"})()
    plan = aurora_detail_authored.normalize_strategy(aurora_detail_authored.fake_strategy(request))
    plan["plan"]["product_identity_physics_lock"]["primary_product_source"] = 9
    aurora_detail_authored.validate_source_selection(plan, ("style_reference", "product_reference"))
    assert plan["plan"]["product_identity_physics_lock"]["primary_product_source"] == 2
    aurora_detail_authored.validate_strategy(plan, 2)
