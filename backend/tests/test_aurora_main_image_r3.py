"""Round 3: poster banners never ship, and no headline fact on two pages.

Facts come from validation job job_cff3069ee92b4ffc90af84469c96812a: its
search cover kept the source poster's 「【新品上市】」 banner and pages 2 and 6
both led with 「260g 大容量」.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app import label_fidelity
from app.aurora_main_image_provider import (
    _copy_authority,
    _unauthorized_offproduct_lines,
    _with_source_copy,
)
from app.xinghe_agent import FakeXingheGateway, PlannerCallResult, PlannerRequest
from tests.test_aurora_main_image_quickwins import _compiled_session
from tests.test_aurora_main_image_round2 import _run_pages
from tests.test_label_fidelity import REFERENCE, _MainLabelGateway

FACTS = {
    "selling_points": [
        "烟酰胺·色淡林精华配方",
        "7天美白，一润到底",
        "浮光栀子香，精致香氛",
        "260g 大容量",
    ],
    "display_facts": ["260g"],
}
SETTINGS = {"product_name": "OLAY超白瓶美白身体乳"}
POSTER_TEXT = [
    "7天美白，一润到底",
    "密集美白",
    "改善顽固色沉",
    "【新品上市】｜OLAY超白瓶美白身体乳",
    "260g",
]


# 2. Headline facts ---------------------------------------------------------


def test_spec_headline_only_on_the_closure_page_and_no_repeated_headline(
    tmp_path: Path,
) -> None:
    pages = _compiled_session(tmp_path)["plan"]["pages"]
    leads = [page["primary_claim"] for page in pages]
    seeds = [
        page["display_copy_contract"]["headline_seed_source_segment"] for page in pages
    ]
    assert leads[5] == "260g 大容量"
    assert "260g 大容量" not in leads[:5]
    assert len(set(seeds)) == 6, seeds
    for page in pages[1:5]:
        assert "260g 大容量" not in page["claim_bundle"]
    # With four distinct facts, two carousel pages must recycle a fact, but
    # never on neighbouring pages.
    for left, right in zip(leads, leads[1:], strict=False):
        assert left != right


# 1. Source-image copy is a user fact (original Skill core policy) -------------


def test_source_image_copy_is_authorized_and_only_invented_text_is_rejected() -> None:
    facts = _with_source_copy(FACTS, POSTER_TEXT)
    authority = _copy_authority(facts, SETTINGS)
    found = _unauthorized_offproduct_lines(
        [
            *POSTER_TEXT,
            "【新品上市】",
            "7天美白 一润到底",
            "烟酰胺·色淡林 精华配方",
            "医学级美白",
            "精华身体乳",
        ],
        authority,
    )
    assert found == ["医学级美白", "精华身体乳"]
    assert "【新品上市】｜OLAY超白瓶美白身体乳" in facts["display_facts"]


class _SourceCopyGateway(_MainLabelGateway):
    """The source poster carries 新品上市; page 0's first draft invents a claim."""

    def __init__(self, page_readings: list[list[str]]) -> None:
        super().__init__([], fail_page1_audit=False)
        self.page_readings = list(page_readings)

    def poster_reading(self) -> dict[str, Any]:
        return {
            "products": [{"label_lines": REFERENCE}],
            "other_text_lines": [*POSTER_TEXT, "模糊?字"],
        }

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        if (
            request.planning_profile == label_fidelity.READ_PROFILE
            and ":poster-text" not in request.idempotency_key
        ):
            result = await FakeXingheGateway.plan(self, request)
            other = self.page_readings.pop(0) if self.page_readings else []
            payload = {
                "products": [{"label_lines": REFERENCE}],
                "other_text_lines": other,
            }
            return replace(result, payload=payload)
        return await super().plan(request)


def test_source_copy_joins_the_pool_and_invented_text_triggers_the_repair(
    tmp_path: Path,
) -> None:
    gateway = _SourceCopyGateway(
        [
            ["7天美白", "【新品上市】", "医学级美白"],  # page 0 draft invents
            ["7天美白", "【新品上市】"],  # page 0 repair: source copy only
            ["260g 大容量"],
        ]
    )
    settings = {
        "product_name": "OLAY超白瓶美白身体乳",
        "selling_points": FACTS["selling_points"],
        "user_provided_display_facts": FACTS["display_facts"],
    }
    provider, results = _run_pages(
        tmp_path,
        gateway,  # type: ignore[arg-type]
        configuration={"job": {"settings": settings}},
    )

    first_prompt = gateway.image_calls[0].prompt
    assert "【清除原海报文字】" not in first_prompt
    page0 = [v for v in provider.state["generated_versions"] if v["page_index"] == 0]
    assert len(page0) == 2
    excluded = provider.state["excluded_generated_assets"][0]
    assert "no_unsupported_claim" in excluded["failed_checks"]
    repair_prompt = gateway.image_calls[1].prompt
    assert "「医学级美白」" in repair_prompt
    assert "「【新品上市】」" not in repair_prompt
    assert results[0].artifact is not None
    assert results[0].artifact.sha256 == page0[1]["sha256"]
    workspace = provider._workspace(provider.state["request_id"])
    cached = json.loads((workspace / "source-image-copy.json").read_text("utf-8"))
    assert "【新品上市】｜OLAY超白瓶美白身体乳" in cached["lines"]
    assert "模糊?字" not in cached["lines"]  # obscured text is never guessed
    request = json.loads(
        (workspace / "generation-page-1-attempt-1.json").read_text("utf-8")
    )
    assert "密集美白" in request["authorized_facts"]["display_facts"]
