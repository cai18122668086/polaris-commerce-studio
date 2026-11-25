"""Main image authored in one pass (detail-page / replica style), no pixel review."""

from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import select

from app import aurora_main_image_authored as authored
from app.aurora_main_image_planner import PAGE_ROLES
from app.config import default_aurora_v20_skill_root
from app.models import CreditReservationRecord, JobPlanRecord
from app.xinghe_agent import FakeXingheGateway

from ._main_image_workflow_helpers import assert_delivery, confirm, detail
from ._main_image_workflow_helpers import Gateway as SyntheticSuiteGateway
from .test_api import dispatch_pending
from .test_aurora_main_image_native_fast_workflow import create


class AuthoredGateway(SyntheticSuiteGateway):
    def __init__(self, payload=None):
        super().__init__()
        self.payload = payload

    async def plan(self, request):
        assert request.planning_profile == authored.PROFILE
        result = await FakeXingheGateway.plan(self, request)
        self.planner_calls[-1] = request
        if self.payload is not None:
            result = replace(result, payload=deepcopy(self.payload))
        return result

    async def edit(self, request):
        result = await super().edit(request)
        return replace(
            result, provider_request_id=f"{result.provider_request_id}:{request.job_id}"
        )


def _stored_plan(client, job_id):
    with client.app.state.session_factory() as db:
        row = db.scalar(select(JobPlanRecord).where(JobPlanRecord.job_id == job_id))
        return row.schema_version, deepcopy(row.payload)


@pytest.mark.parametrize("auto", [True, False])
def test_one_planning_call_six_parallel_images_no_review(client, tmp_path, auto):
    job_id, gateway = create(client, tmp_path, auto=auto, gateway=AuthoredGateway())
    dispatch_pending(client)
    if not auto:
        assert detail(client, job_id)["status"] == "awaiting_confirmation"
        assert not gateway.image_calls
        confirm(client, job_id)
        dispatch_pending(client)
    current = assert_delivery(client, job_id)
    schema_version, stored = _stored_plan(client, job_id)
    assert schema_version == authored.SCHEMA_VERSION
    assert stored["version"] == authored.VERSION
    assert stored["skill_id"] == authored.REFERENCE_ID
    assert stored["skill_content_hash"] == authored.reference_bundle()[1]
    assert stored["validation"]["visual_review"] == "NOT_REVIEWED"
    assert [page["page_role"] for page in stored["pages"]] == list(PAGE_ROLES)

    # One planning call (identity, facts, transcription and six prompts) …
    assert len(gateway.planner_calls) == 1
    call = gateway.planner_calls[0]
    for name in ("core-policy.md", "six-page-strategy.md", "commercial-performance.md"):
        text = (default_aurora_v20_skill_root() / "references" / name).read_text(
            encoding="utf-8"
        )
        assert text.strip() in call.system_prompt
    # … then exactly six image calls with the frozen server-joined prompts.
    assert len(gateway.image_calls) == 6
    strategy = stored["_authored_strategy"]
    for request in gateway.image_calls:
        index = request.page_number - 1
        page = stored["pages"][index]
        assert request.prompt == page["prompt"] == authored.compile_prompt(strategy, index)
        assert [s.asset_id for s in request.sources] == page["source_asset_ids"]
        assert request.size == "1024x1024" and request.quality == "high"
    assert current["cost"]["actual_credits"] == 48
    with client.app.state.session_factory() as db:
        reservation = db.scalar(
            select(CreditReservationRecord).where(
                CreditReservationRecord.job_id == job_id
            )
        )
        assert reservation.status == "settled" and reservation.settled_credits == 48

    # The workspace sees the plan, never prompts, sources or private strategy.
    public = current["plan"]["payload"]
    assert "prompt" not in str(public)
    assert "_authored_strategy" not in public
    assert all("source_asset_ids" not in page for page in public["pages"])
    assert all(page["main_selling_point"] for page in public["pages"])


def test_incomplete_plan_fails_planning_without_images(client, tmp_path):
    broken = authored.fake_strategy("轻量随行杯", 1)
    broken["plan"]["pages"][1]["page_role"] = PAGE_ROLES[0]
    job_id, gateway = create(client, tmp_path, gateway=AuthoredGateway(broken))
    dispatch_pending(client)
    current = detail(client, job_id)
    assert current["status"] == "failed"
    assert current["stage"] == "planning_failed"
    assert not gateway.image_calls
    assert current["cost"]["actual_credits"] == 0


def test_strategy_validation_rejects_unusable_plans():
    good = authored.fake_strategy("湿纸巾", 3)
    assert authored.validate_strategy(good, 3)["plan"]["pages"][0]["page_role"] == (
        PAGE_ROLES[0]
    )
    cases = []
    swapped = deepcopy(good)
    swapped["plan"]["pages"][0], swapped["plan"]["pages"][1] = (
        swapped["plan"]["pages"][1],
        swapped["plan"]["pages"][0],
    )
    cases.append(swapped)
    out_of_range = deepcopy(good)
    out_of_range["plan"]["pages"][2]["reference_sources"] = [4]
    cases.append(out_of_range)
    primary = deepcopy(good)
    primary["plan"]["product_identity_lock"]["primary_product_source"] = 9
    cases.append(primary)
    duplicate = deepcopy(good)
    duplicate["plan"]["pages"][3]["page_prompt"] = duplicate["plan"]["pages"][2][
        "page_prompt"
    ]
    cases.append(duplicate)
    missing = deepcopy(good)
    del missing["plan"]["pages"][4]["scene"]
    cases.append(missing)
    for case in cases:
        with pytest.raises(authored.AuthoredPlanError):
            authored.validate_strategy(case, 3)


def test_prompt_joins_shared_locks_and_page_fields_verbatim():
    strategy = authored.validate_strategy(authored.fake_strategy("湿纸巾", 2), 2)
    strategy["analysis"]["confirmed_facts"] = ["80抽/包", "湿巾尺寸：140×180mm"]
    prompt = authored.compile_prompt(strategy, 3)
    page = strategy["plan"]["pages"][3]
    assert prompt.startswith(authored._PREFIX)
    assert authored._BOUNDARIES in prompt
    assert "湿巾尺寸：140×180mm" in prompt
    assert page["scene"] in prompt and page["camera"] in prompt
    assert prompt.endswith("IMAGE BRIEF: " + page["page_prompt"].strip())
    assert authored.PAGE_DUTIES[3] in prompt
    # Executable plumbing never reaches the image model.
    assert "reference_sources" not in prompt and "primary_product_source" not in prompt


def test_page_sources_put_the_page_choice_first_and_keep_the_primary():
    strategy = authored.validate_strategy(authored.fake_strategy("湿纸巾", 5), 5)
    strategy["plan"]["product_identity_lock"]["primary_product_source"] = 3
    strategy["plan"]["pages"][4]["reference_sources"] = [5, 2]
    ids = ["a1", "a2", "a3", "a4", "a5"]
    assert authored.page_source_ids(strategy, 4, ids) == ["a5", "a2", "a3"]
    strategy["plan"]["pages"][0]["reference_sources"] = [3]
    assert authored.page_source_ids(strategy, 0, ids) == ["a3"]
