"""Product-label fidelity gate (W, 2026-11-25).

Fixtures are the blind label reads of agent V's real final-acceptance outputs
(V/最终验收), recorded through the production gate code path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app import label_fidelity, refined_detail
from app.aurora_main_image_provider import _inject_label_failure
from app.provider import ProviderArtifact, ProviderOutcome, ProviderRequest
from app.xinghe_agent import (
    FakeXingheGateway,
    ImageCallResult,
    ImageEditRequest,
    PlannerCallResult,
    PlannerRequest,
    SourceImage,
    XingheImageProvider,
    _planner_prompt,
    _planner_response_format,
    normalize_usage,
)
from tests.test_aurora_main_image_round2 import _run_pages

FIXTURE = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "label_fidelity"
        / "v_final_acceptance.json"
    ).read_text(encoding="utf-8")
)
REFERENCE = FIXTURE["reference"]["label_lines"]
PAGES = FIXTURE["pages"]


def _verdict(name: str) -> label_fidelity.LabelVerdict:
    page = PAGES[name]
    return label_fidelity.compare(REFERENCE, page["products"], page["other_text_lines"])


# 1. Char-exact comparison on V's real outputs ---------------------------------


@pytest.mark.parametrize(
    "name",
    ["detail_p2", "xb_detail_p2", "main_p2_repaired", "main_r1_p1_callout"],
)
def test_gate_detects_the_label_typos_of_the_final_acceptance_run(name: str) -> None:
    verdict = _verdict(name)

    assert verdict.status == "MISMATCH"
    assert [
        [item.expected, item.seen, item.where] for item in verdict.mismatches
    ] == PAGES[name]["expect"]


def test_gate_detects_each_reported_character() -> None:
    # 精华 vs 精光, 颜色不均 vs 顽固色沉, 瓶 vs 栀.
    assert "「精华身体乳」应为「精光身体乳」" in _verdict("detail_p2").summary()
    assert "「改善顏色不均」应为「改善顽固色沉」" in _verdict("xb_detail_p2").summary()
    assert "「浮光瓶子香」应为「浮光栀子香」" in _verdict("main_p2_repaired").summary()


@pytest.mark.parametrize(
    "name", ["main_p2_draft", "detail_p3_traditional_reading", "xb_detail_p1"]
)
def test_correct_labels_pass_including_traditional_glyph_readings(name: str) -> None:
    verdict = _verdict(name)

    assert verdict.status == "PASS"
    assert set(verdict.verified_lines) == set(REFERENCE)


def test_traditional_fold_keeps_a_different_character_different() -> None:
    # 頑 is the Traditional form of 顽 (same word); 顏 is the form of 颜.
    assert label_fidelity.normalize_line("改善頑固色沉") == "改善顽固色沉"
    assert label_fidelity.normalize_line("改善顏色不均") != "改善顽固色沉"
    assert label_fidelity.normalize_line("浮光梔子香") == "浮光栀子香"
    assert label_fidelity.normalize_line("烟酰胺 ・ 色淡林") == "烟酰胺·色淡林"


def test_illegible_partial_and_unrelated_lines_are_not_mismatches() -> None:
    assert label_fidelity.compare(REFERENCE, [], []).status == "UNCHECKED"
    assert label_fidelity.compare(REFERENCE, [["浮光?子香"]]).status == "UNCHECKED"
    # A partial read (occlusion/crop) is neither verified nor a typo.
    assert label_fidelity.compare(REFERENCE, [["精光身体"]]).status == "UNCHECKED"
    # Merged lines and unrelated product text are fine.
    merged = label_fidelity.compare(
        REFERENCE, [["OLAY", "精光身体乳浮光栀子香", "260g"]]
    )
    assert merged.status == "PASS"
    # Off-product copy that merely contains or ignores label wording passes.
    assert (
        label_fidelity.compare(
            REFERENCE,
            [["精光身体乳"]],
            ["OLAY超白瓶美白身体乳", "浮光栀子香，精致香氛", "烟酰胺·色淡林 精华配方"],
        ).status
        == "PASS"
    )
    assert (
        label_fidelity.compare([], [["anything"]]).reason
        == "reference_has_no_label_text"
    )


# 2. Transport contract ---------------------------------------------------------


def _png(size: tuple[int, int], shade: int = 200) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (shade, 180, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_page_is_read_from_four_native_resolution_tiles() -> None:
    tiles = label_fidelity.page_tiles(_png((1440, 1920)))

    # The primary vision endpoint rejects five-image requests.
    assert len(tiles) == 4
    sizes = {Image.open(BytesIO(tile)).size for tile in tiles}
    assert sizes == {(768, 1024)}  # 972x1296 crops, capped at 1024 px


def test_read_request_is_blind_and_strict() -> None:
    request = PlannerRequest(
        workspace_id="w",
        job_id="j",
        group_key="g",
        sources=(),
        page_count=1,
        language="zh-CN",
        product_name="x",
        product_information=(),
        platform_code="LABEL_FIDELITY",
        size="1024x1024",
        idempotency_key="k",
        planning_profile=label_fidelity.READ_PROFILE,
    )
    text = _planner_prompt(request)
    # The expected label never reaches the reader.
    assert not any(line in text for line in REFERENCE)
    schema = _planner_response_format(request)["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["required"] == ["products", "other_text_lines"]


# 3. Detail pipelines: one targeted repair, never a loop -----------------------


class _ScriptedGateway(FakeXingheGateway):
    provider_name = "scripted"

    def __init__(
        self, readings: list[dict[str, Any]], *, repair_ok: bool = True
    ) -> None:
        super().__init__()
        self.readings = list(readings)
        self.repair_ok = repair_ok
        self.label_calls: list[PlannerRequest] = []

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        if request.planning_profile not in label_fidelity.PROFILES:
            return await super().plan(request)
        self.label_calls.append(request)
        payload: dict[str, Any] = (
            {"label_lines": REFERENCE}
            if request.planning_profile == label_fidelity.REFERENCE_PROFILE
            else self.readings.pop(0)
        )
        usage = {"input_tokens": 8000, "output_tokens": 350}
        return PlannerCallResult(
            payload=payload,
            provider_request_id="scripted",
            raw_usage=usage,
            normalized_usage=normalize_usage(usage),
            api_latency_seconds=0.0,
            actual_cost_micros=12_000,
        )

    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        self.image_calls.append(request)
        if not self.repair_ok:
            return ImageCallResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                api_latency_seconds=0,
                actual_cost_micros=None,
                error_code="IMAGE_PROVIDER_FAILED",
            )
        return _image_result(_png((1440, 1920), shade=90))


def _artifact(payload: bytes) -> ProviderArtifact:
    return ProviderArtifact(
        payload=payload,
        filename="page.png",
        content_type="image/png",
        width=1440,
        height=1920,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _image_result(payload: bytes) -> ImageCallResult:
    return ImageCallResult(
        outcome=ProviderOutcome.SUCCEEDED,
        provider_request_id="img",
        raw_usage={"network_requests": 1},
        normalized_usage=normalize_usage(None),
        api_latency_seconds=1.0,
        actual_cost_micros=90_000,
        artifact=_artifact(payload),
    )


def _reading(name: str) -> dict[str, Any]:
    page = PAGES[name]
    return {
        "products": [{"label_lines": lines} for lines in page["products"]],
        "other_text_lines": page["other_text_lines"],
    }


def _run_detail_gate(
    tmp_path: Path, gateway: _ScriptedGateway
) -> tuple[ImageCallResult, ImageCallResult]:
    provider = XingheImageProvider(
        None,  # type: ignore[arg-type]
        gateway,
        storage=None,
        skill_root=tmp_path,
        max_concurrency=2,
        skill_id=refined_detail.SKILL_ID,
    )
    assert provider.label_gate_enabled
    reference = _png((1254, 1254), shade=250)
    sources = (
        SourceImage(
            asset_id="asset_product",
            group_key="primary-product",
            filename="product.png",
            content_type="image/png",
            sha256=hashlib.sha256(reference).hexdigest(),
            payload=reference,
        ),
    )
    image_request = ImageEditRequest(
        workspace_id="ws",
        job_id=f"job_{tmp_path.name}",
        job_item_id="item",
        attempt_id="attempt",
        page_number=2,
        group_key="primary-product",
        sources=sources,
        prompt="vertical 3:4 e-commerce detail page image",
        quality="high",
        idempotency_key="detail-p2",
        size="1440x1920",
    )
    request = ProviderRequest(
        workspace_id="ws",
        job_id=image_request.job_id,
        job_item_id="item",
        attempt_id="attempt",
        operation="detail_pack",
        idempotency_key="detail-p2",
        configuration={},
    )
    generated = _image_result(_png((1440, 1920), shade=200))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(label_fidelity, "default_cache_root", lambda: tmp_path / "lf")
        gated = asyncio.run(
            provider._label_fidelity_gate(request, image_request, sources, generated)
        )
    return generated, gated


def test_detail_label_typo_gets_one_targeted_repair(tmp_path: Path) -> None:
    gateway = _ScriptedGateway([_reading("detail_p2"), _reading("xb_detail_p1")])
    generated, gated = _run_detail_gate(tmp_path, gateway)

    assert len(gateway.image_calls) == 1
    repair = gateway.image_calls[0]
    assert repair.sources[0].source_role == "label_repair_canvas"
    assert repair.sources[0].payload == generated.artifact.payload  # type: ignore[union-attr]
    assert repair.sources[1].source_role == "product_reference"
    assert "「精华身体乳」逐字改为「精光身体乳」" in repair.prompt
    assert "【标签锁定】" in repair.prompt
    assert gated.artifact is not None and gated.artifact != generated.artifact
    record = gated.raw_usage["metrics"]["label_fidelity"]  # type: ignore[index]
    assert record["status"] == "REPAIRED"
    assert record["delivered"] == "label_repair"
    # 1 reference transcription + 2 page reads + 1 repair image.
    assert gated.raw_usage["network_requests"] == 1 + 3 + 1  # type: ignore[index]
    assert gated.actual_cost_micros == 90_000 + 3 * 12_000 + 90_000


def test_detail_label_still_wrong_after_repair_is_disclosed_not_looped(
    tmp_path: Path,
) -> None:
    worse = _reading("xb_detail_p2")
    worse["products"][0]["label_lines"] = [
        "精华身体乳",
        "改善颜色不均",
    ]
    gateway = _ScriptedGateway([_reading("xb_detail_p2"), worse])
    generated, gated = _run_detail_gate(tmp_path, gateway)

    assert len(gateway.image_calls) == 1  # exactly one repair
    record = gated.raw_usage["metrics"]["label_fidelity"]  # type: ignore[index]
    assert record["status"] == "RESIDUAL"
    # The repair made it worse, so the better (generated) page is delivered.
    assert record["delivered"] == "generated"
    assert gated.artifact == generated.artifact
    assert "改善顽固色沉" in record["residual"]


def test_detail_correct_label_costs_one_read_per_page(tmp_path: Path) -> None:
    gateway = _ScriptedGateway(
        [_reading("xb_detail_p1"), _reading("detail_p3_traditional_reading")]
    )
    _, first = _run_detail_gate(tmp_path, gateway)
    assert first.raw_usage["metrics"]["label_fidelity"]["status"] == "PASS"  # type: ignore[index]
    reference_calls = [
        call
        for call in gateway.label_calls
        if call.planning_profile == label_fidelity.REFERENCE_PROFILE
    ]
    assert len(reference_calls) == 1
    assert gateway.image_calls == []


def test_failed_repair_call_keeps_the_page_and_discloses(tmp_path: Path) -> None:
    gateway = _ScriptedGateway([_reading("detail_p2")], repair_ok=False)
    generated, gated = _run_detail_gate(tmp_path, gateway)

    assert gated.outcome == ProviderOutcome.SUCCEEDED
    assert gated.artifact == generated.artifact
    record = gated.raw_usage["metrics"]["label_fidelity"]  # type: ignore[index]
    assert record["status"] == "RESIDUAL"
    assert record["repaired"]["status"] == "REPAIR_UNAVAILABLE"


def test_reference_label_is_transcribed_once_per_job(tmp_path: Path) -> None:
    gateway = _ScriptedGateway([])
    gate = label_fidelity.LabelFidelityGate(gateway, cache_root=tmp_path)
    reference = _png((600, 600))
    source = SourceImage(
        asset_id="a",
        group_key="g",
        filename="p.png",
        content_type="image/png",
        sha256=hashlib.sha256(reference).hexdigest(),
        payload=reference,
    )

    async def twice() -> list[tuple[str, ...] | None]:
        account = label_fidelity.GateAccount()
        return [
            await gate.reference_lines(
                workspace_id="w",
                job_id="job_once",
                idempotency_key="job_once",
                references=[source],
                account=account,
            )
            for _ in range(2)
        ]

    first, second = asyncio.run(twice())
    # A second gate (another worker process) reads the same on-disk cache.
    other = label_fidelity.LabelFidelityGate(gateway, cache_root=tmp_path)
    third = asyncio.run(
        other.reference_lines(
            workspace_id="w",
            job_id="job_once",
            idempotency_key="job_once",
            references=[source],
            account=label_fidelity.GateAccount(),
        )
    )
    assert first == second == third == tuple(REFERENCE)
    assert len(gateway.label_calls) == 1


# 4. Main six-pack: the blind read decides label_exact ------------------------


class _MainLabelGateway(FakeXingheGateway):
    """Page 1's first audit fails; its repair prints 浮光瓶子香.

    The model repair check parrots the reference (label_exact true), exactly
    as on 2026-11-25; the blind read must overrule it.
    """

    provider_name = "scripted"

    def poster_reading(self) -> dict[str, Any]:
        return {"products": [{"label_lines": REFERENCE}], "other_text_lines": []}

    def __init__(self, readings: list[str], *, fail_page1_audit: bool) -> None:
        super().__init__()
        self.readings = list(readings)
        self.fail_page1_audit = fail_page1_audit
        self.audits_by_page: dict[int, int] = {}
        self.reference_calls: list[PlannerRequest] = []

    async def edit(self, request: Any) -> Any:
        result = await super().edit(request)
        shade = (len(self.image_calls) * 37) % 255
        data = _png((1024, 1024), shade)
        artifact = replace(
            result.artifact,
            payload=data,
            sha256=hashlib.sha256(data).hexdigest(),
            content_type="image/png",
        )
        return replace(
            result,
            artifact=artifact,
            raw_usage={**(result.raw_usage or {}), "network_requests": 1},
        )

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        if request.planning_profile == label_fidelity.REFERENCE_PROFILE:
            self.reference_calls.append(request)
            result = await super().plan(request)
            return replace(result, payload={"label_lines": REFERENCE})
        if request.planning_profile == label_fidelity.READ_PROFILE:
            result = await super().plan(request)
            if ":poster-text" in request.idempotency_key:
                # The one per-job read of the source poster's off-product text.
                return replace(result, payload=self.poster_reading())
            return replace(result, payload=_reading(self.readings.pop(0)))
        result = await super().plan(request)
        if request.planning_profile == "aurora_repair_identity_check":
            payload = dict(result.payload or {})
            for key in ("pre_repair", "repaired"):
                payload[key] = {
                    **payload[key],
                    "label_exact": True,
                    "label_text_seen": "；".join(REFERENCE),
                }
            return replace(result, payload=payload)
        if request.planning_profile != "aurora_v20_visual_audit":
            return result
        page = request.page_count - 1
        self.audits_by_page[page] = self.audits_by_page.get(page, 0) + 1
        if self.fail_page1_audit and page == 1 and self.audits_by_page[page] == 1:
            payload = dict(result.payload or {})
            checks = [dict(item) for item in payload["checks"]]
            for item in checks:
                if item["name"] == "evidence_relation_visible":
                    item.update(passed=False, score=40)
            payload["checks"] = checks
            payload["all_material_deficiencies"] = [
                {
                    "check": "evidence_relation_visible",
                    "visible_problem": "容量卖点没有可见的使用或比例关系",
                    "root_cause": "商品孤立摆放在台面上",
                    "required_change": "加入可信的使用场景表现容量",
                }
            ]
            return replace(result, payload=payload)
        return result


def test_main_repair_that_rewrites_fine_print_keeps_the_draft(tmp_path: Path) -> None:
    # p1 draft reads correctly; its repair prints 浮光瓶子香 (V's p2).
    gateway = _MainLabelGateway(
        ["main_p2_draft", "main_p2_draft", "main_p2_repaired"], fail_page1_audit=True
    )
    provider, results = _run_pages(tmp_path, gateway)  # type: ignore[arg-type]

    page = results[1]
    versions = [v for v in provider.state["generated_versions"] if v["page_index"] == 1]
    draft, repair = versions
    assert repair["status"] == "REJECTED_IDENTITY_REGRESSION"
    assert page.artifact is not None and page.artifact.sha256 == draft["sha256"]
    check = repair["post_repair_identity_check"]
    assert check["repaired"]["label_exact"] is False
    assert "浮光瓶子香" in check["repaired"]["label_text_seen"]
    assert check["pre_repair"]["label_exact"] is True
    record = page.raw_usage["metrics"]["label_fidelity"]  # type: ignore[index]
    assert record["status"] == "PASS"


def test_main_label_typo_on_a_passing_page_triggers_the_one_repair(
    tmp_path: Path,
) -> None:
    # p1 passes the broad audit but its label reads 精华身体乳.
    gateway = _MainLabelGateway(
        ["main_p2_draft", "detail_p2", "main_p2_draft"], fail_page1_audit=False
    )
    provider, results = _run_pages(tmp_path, gateway)  # type: ignore[arg-type]

    page = results[1]
    versions = [v for v in provider.state["generated_versions"] if v["page_index"] == 1]
    assert len(versions) == 2  # one repair, no loop
    repair_prompt = gateway.image_calls[-1].prompt
    assert "「精华身体乳」→「精光身体乳」" in repair_prompt
    assert "【返修标签锁定】" in repair_prompt
    assert page.artifact is not None and page.artifact.sha256 == versions[1]["sha256"]
    record = page.raw_usage["metrics"]["label_fidelity"]  # type: ignore[index]
    assert record["status"] == "REPAIRED"
    excluded = provider.state["excluded_generated_assets"]
    assert any("factual_copy_match" in item["failed_checks"] for item in excluded)
    # The repair request lists the failed draft first; the label reference
    # must still be the original product, transcribed once for the job.
    assert len(gateway.reference_calls) == 1


def test_injected_label_failure_is_a_valid_targeted_repair() -> None:
    judgment: dict[str, Any] = {
        "checks": [
            {
                "name": "factual_copy_match",
                "passed": True,
                "score": 92,
                "material": True,
                "observed_evidence": "文案均来自授权事实",
            },
        ],
        "all_material_deficiencies": [],
    }
    _inject_label_failure(judgment, _verdict("main_p2_repaired"))

    check = judgment["checks"][0]
    assert check["passed"] is False and check["score"] == 40
    deficiency = judgment["all_material_deficiencies"][0]
    assert deficiency["check"] == "factual_copy_match"
    assert "「浮光瓶子香」→「浮光栀子香」" in deficiency["required_change"]
    assert judgment["label_fidelity_gate"]["status"] == "MISMATCH"
