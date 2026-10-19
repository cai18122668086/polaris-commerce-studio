"""The small website brief reaches the existing native generation/delivery path."""

import json
from io import BytesIO
from zipfile import ZipFile
from copy import deepcopy

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
            "approval_text": "我已逐屏审阅本次合成任务的最终结果，并接受明确列出的残差。",
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
