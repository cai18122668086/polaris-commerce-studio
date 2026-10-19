"""The small website brief reaches the existing native generation/delivery path."""

import json
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.aurora_detail_runtime import detail_workspace
from app.domestic_detail import direct
from app.domestic_detail.plans import resolve_native_plan
from app.xinghe_agent import validate_editable_plan_payload
from tests.test_api import WORKSPACE_ID, idem
from tests.test_domestic_detail_execution import _gateway
from tests.test_domestic_detail_website_v1 import (
    explicit_synthetic_storage,  # noqa: F401
    generate,
    planned,
)


def test_direct_brief_compiles_once_and_persists_four_native_pairs(client):
    job = planned(client, profile=direct.VERSION)
    calls = _gateway(client).planner_calls
    assert len(calls) == 2
    assert [call.authoring_stage for call in calls] == ["", "direct"]
    assert resolve_native_plan(job["plan"]["payload"])["plan_format"] == direct.VERSION
    assert validate_editable_plan_payload(job["plan"]["payload"], 8) == []
    current = generate(client, job)
    assert current["status"] == "awaiting_final_review", current
    assert len(_gateway(client).image_calls) == 4
    root = detail_workspace(job["id"])
    state = json.loads((root / "session.json").read_bytes())
    assert state["plan"]["planning_mode"] == direct.VERSION
    assert len(state["modules"]) == 8
    assert all(module["accepted_asset"] for module in state["modules"])
    assert all(len(module["attempts"]) == 1 for module in state["modules"])
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/detail-final-review"
    )
    assert response.status_code == 200, response.text
    assert len(current["assets"]) > 8
    final = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/finalize",
        headers=idem(),
        json={
            "approval_text": (
                "我已逐屏审阅本次合成任务的最终结果，并接受明确列出的残差。"
            ),
            "final_review_sha256": response.json()["sha256"],
        },
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "completed"
    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/deliverables.zip"
    )
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as package:
        assert (
            len([name for name in package.namelist() if name.startswith("screens/")])
            == 8
        )
    assert len(_gateway(client).image_calls) == 4


def test_direct_brief_cannot_add_fact_ids_or_silently_drop_user_points(client):
    job = planned(client, profile=direct.VERSION)
    request = _gateway(client).planner_calls[-1]
    value = deepcopy(resolve_native_plan(job["plan"]["payload"])["website_brief"])
    value["screens"][0]["fact_ids"] = ["INVENTED"]
    assert direct.errors(value, request)
    value = deepcopy(resolve_native_plan(job["plan"]["payload"])["website_brief"])
    first = direct.facts_for(request)[1][0]
    for screen in value["screens"]:
        screen["fact_ids"] = [first]
    assert any("coverage" in message for message in direct.errors(value, request))


def test_confirmed_history_keeps_human_evidence_and_rejects_changed_truth():
    from app.domestic_detail.facts import DetailIntakeError
    from app.domestic_detail.intake import preserve_confirmed_history

    conflict = {
        "id": "C01",
        "topic": "颜色",
        "alternative_fact_ids": ["F01", "O01"],
        "why_material": "原始颜色冲突说明",
        "status": "UNRESOLVED",
    }
    prior = {
        "source_conflicts": [conflict],
        "observed_facts": [{"id": "O01", "text": "近黑鞋面"}],
    }
    resolution = {
        "confirmation_text": "确认深棕色",
        "source_intake": prior,
        "resolutions": [
            {
                "conflict_id": "C01",
                "retained_fact_ids": ["F01"],
                "rejected_fact_ids": ["O01"],
            }
        ],
    }
    reply = deepcopy(prior)
    reply["source_conflicts"][0].update(
        why_material="模型改写了历史说明",
        resolution={
            "retained_fact_ids": ["F01"],
            "rejected_fact_ids": ["O01"],
            "confirmation_text": "确认深棕色",
        },
    )
    raw = deepcopy(reply)
    settings = {"website_contract_version": direct.VERSION}
    canonical, receipt = preserve_confirmed_history(reply, settings, resolution)
    assert canonical == prior
    assert reply == raw
    assert receipt["version"] == "website-confirmed-history-v1"
    assert preserve_confirmed_history(reply, {}, resolution) == (raw, None)
    for field in ("fact", "alternative", "choice"):
        changed = deepcopy(reply)
        if field == "fact":
            changed["observed_facts"][0]["text"] = "模型换成红色鞋面"
        elif field == "alternative":
            changed["source_conflicts"][0]["alternative_fact_ids"] = ["F01", "O02"]
        else:
            changed["source_conflicts"][0]["resolution"]["retained_fact_ids"] = ["O01"]
        with pytest.raises(DetailIntakeError, match="changed"):
            preserve_confirmed_history(changed, settings, resolution)


def test_adjacent_edges_map_to_actual_pair_seams_without_rewriting(client):
    from dataclasses import replace

    planned(client, profile=direct.VERSION)
    original_request = _gateway(client).planner_calls[-1]
    for count in (8, 10, 12):
        request = replace(original_request, page_count=count)
        brief = direct.mock_brief(request)
        pair_order = deepcopy(brief)
        assert direct.errors(pair_order, request) == []
        edges = [f"屏幕 {i + 1} 到 {i + 2} 的背景衔接" for i in range(count - 1)]
        brief["pair_transitions"] = edges
        assert direct.errors(brief, request) == []
        plan = direct.build(brief, request)
        assert brief["pair_transitions"] == edges
        pairs = plan["output_strategy"]["continuous_pair_rendering"]["pair_ids"]
        assert [pair["internal_seam_carrier"] for pair in pairs] == edges[::2]
        direct.validate_plan(plan, count)
        brief["pair_transitions"] = edges[:-1]
        assert direct.errors(brief, request)
