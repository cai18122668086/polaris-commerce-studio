"""Missing vision-envelope fields must not cause another image generation."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.aurora_detail_runtime import AuroraDetailHarnessRunner
from app.models import JobPlanRecord
from app.provider import ProviderRequest
from app.xinghe_agent import (
    FakeXingheGateway,
    PlannerCallResult,
    SourceImage,
    XingheAgentError,
    XingheImageProvider,
    _artifact_from_bytes,
    _planner_prompt,
    _planner_response_format,
    normalize_usage,
)
from tests.test_api import WORKSPACE_ID, dispatch_pending, upload_asset
from tests.test_domestic_detail_execution import _create_detail_job


@pytest.mark.parametrize(
    "mode", ["missing", "partial_failed", "invalid_followup", "complete_failed"]
)
def test_native_identity_envelope_repair_is_bounded_and_preserves_failures(
    client, monkeypatch, tmp_path, mode
):
    asset = upload_asset(client, filename="identity-audit-contract.png")
    job = _create_detail_job(
        client, asset["id"], market_region="domestic", auto_start_after_plan=False
    )
    dispatch_pending(client)
    monkeypatch.setattr(
        "app.xinghe_agent.detail_workspace", lambda job_id: tmp_path / job_id
    )

    class AuditGateway(FakeXingheGateway):
        provider_name = "offline-contract-test"

        async def plan(self, request):
            self.planner_calls.append(request)
            if request.planning_profile == "aurora_detail_pair_audit":
                payload = provider._native_detail_judgment(native, artifact)
                payload["status"] = "MATERIAL_FAIL"
                payload["checks"]["internal_seam"]["pass"] = False
                payload["material_failures"] = [
                    {
                        "visible_evidence": (
                            "Black case edge does not cross the declared seam."
                        )
                    }
                ]
                if mode == "complete_failed":
                    payload["identity_silhouette"]["shape_consistent"] = False
                elif mode == "partial_failed":
                    payload["identity_silhouette"] = {"shape_consistent": False}
                else:
                    del payload["identity_silhouette"]
            else:
                assert request.planning_profile == "aurora_detail_identity_audit"
                assert "actual pixels" in _planner_prompt(request)
                schema = _planner_response_format(request)["json_schema"]["schema"]
                assert "shape_consistent" in schema["required"]
                payload = {
                    "shape_consistent": True,
                    "colorway_consistent": True,
                    "texture_consistent": True,
                    "visible_evidence": (
                        "Observed rounded black frame and mint polka-dot surface "
                        "match the originals."
                    ),
                }
                if mode == "invalid_followup":
                    del payload["texture_consistent"]
            return PlannerCallResult(
                payload=payload,
                provider_request_id=f"audit-{len(self.planner_calls)}",
                raw_usage={"total_tokens": 10},
                normalized_usage=normalize_usage({"total_tokens": 10}),
                api_latency_seconds=0.01,
                actual_cost_micros=1,
            )

    gateway = AuditGateway()
    provider = XingheImageProvider(
        client.app.state.session_factory,
        gateway,
        storage=None,
        skill_root=AuroraDetailHarnessRunner().skill_root,
        max_concurrency=1,
        skill_id="aurora-domestic-ecommerce-detail-page",
    )
    buffer = BytesIO()
    Image.new("RGB", (24, 64), "#88cccc").save(buffer, format="PNG")
    artifact = _artifact_from_bytes(
        buffer.getvalue(),
        filename="pair.png",
        expected_size="1440x3840",
        preserve_provider_artifact=True,
    )
    source = SourceImage(
        asset_id="reference",
        group_key="primary",
        filename="reference.png",
        content_type="image/png",
        sha256=artifact.sha256,
        payload=artifact.payload,
        source_role="product_reference",
    )
    native = {
        "pair_id": "P01",
        "module_ids": ["M01", "M02"],
        "pair_render": {"internal_seam_method_id": "EDGE_BLEED"},
    }
    request = ProviderRequest(
        workspace_id=WORKSPACE_ID,
        job_id=job["id"],
        job_item_id="item-test",
        attempt_id="attempt-test",
        operation="detail_pack",
        idempotency_key="audit-test",
        configuration={"group_key": "primary"},
    )
    coroutine = provider._native_detail_judgment_with_review(
        request, native, (source,), artifact
    )
    if mode == "invalid_followup":
        with pytest.raises(XingheAgentError) as error:
            asyncio.run(coroutine)
        assert error.value.code == "AURORA_NATIVE_IDENTITY_AUDIT_INVALID"
    else:
        judgment = asyncio.run(coroutine)
        assert judgment["identity_silhouette"]["shape_consistent"] is (
            mode == "missing"
        )
        assert judgment["checks"]["internal_seam"]["pass"] is False
        assert judgment["status"] == "MATERIAL_FAIL"
    calls = 1 if mode == "complete_failed" else 2
    assert len(gateway.planner_calls) == calls
    assert gateway.image_calls == []
    assert all(
        call.sources[-1].sha256 == artifact.sha256 for call in gateway.planner_calls
    )
    with client.app.state.session_factory() as db:
        plan = db.scalar(select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"]))
        assert len(plan.payload["usage"]["planner"]) == calls + 1
    evidence = list((tmp_path / job["id"]).glob("*.json"))
    assert len(evidence) == calls
    original = next(
        p for p in evidence if p.name.startswith("aurora_detail_pair_audit-")
    )
    if mode in {"missing", "invalid_followup"}:
        assert (
            "identity_silhouette"
            not in json.loads(original.read_text(encoding="utf-8"))["response"]
        )
