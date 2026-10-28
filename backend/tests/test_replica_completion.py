"""Exhausted real native analysis completes automatically, without fake PASSes."""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import AssetRecord, JobAssetRecord, JobRecord, ReplicaDocumentRecord
from app.replica_analysis_recovery import document_file
from app.replica_completion import PLAN, STATE, prepare
from app.replica_exact_compact import CompactExactReplicaRun
from app.replica_native import (
    ReplicaNativeError,
    ReplicaPlanAuditRejected,
    read_json,
    write_json,
)
from app.task_runner import MockTaskRunner
from tests.test_api import dispatch_pending
from tests.test_replica_compact import SyntheticGateway, setup_run


def test_original_v8_checkpoint_keeps_its_protocol_and_plan(tmp_path):
    from app.replica_direct_delivery import V8_BINDING
    from app.replica_exact_compact import protocol_binding, run_class

    current, gateway, payload, records = setup_run(tmp_path)
    legacy_type = run_class("exact", V8_BINDING)
    legacy = legacy_type(
        "exact",
        current.document_id,
        current.workspace_id,
        gateway,
        current.storage,
        root=current.root,
    )
    asyncio.run(legacy.prepare(payload, records))
    snapshot = asyncio.run(legacy.snapshot())
    assert snapshot["model_protocol"] == V8_BINDING
    assert protocol_binding()["version"] == "exact-compact-v9"
    restored = legacy_type(
        "exact",
        current.document_id,
        current.workspace_id,
        gateway,
        current.storage,
        root=current.root,
    )
    asyncio.run(restored.restore(snapshot))
    assert restored.state()["plan_sha256"] == legacy.state()["plan_sha256"]


@pytest.mark.parametrize("unknown", [False, True])
def test_style_unsafe_crops_generate_from_products_without_false_review(
    tmp_path, unknown
):
    from app.replica_completion import execute
    from app.replica_style_delivery import ReplicaDeliveryProvider
    from app.replica_style_evidence import StyleEvidenceInvalid
    from tests.test_replica_resolution import result
    from tests.test_replica_style_analysis import setup_run as style_setup

    run, analysis, refs, payload, records = style_setup(tmp_path)
    run.context.update(
        product_paths=[str(run.root / "inputs/product-00.img")],
        reference_paths=[refs["R01"]["path"]],
    )
    run.journal["cursor"] = {
        "phase": "review",
        "units": [
            {"reference_index": 0, "bbox": [0, 0, 64, 64]},
            {"reference_index": 0, "bbox": [0, 64, 64, 128]},
        ],
        "observation": {"route": "DETAIL_PAGE"},
        "analysis": analysis,
    }
    original = deepcopy(run.state())
    original_analysis = deepcopy(analysis)
    plans = asyncio.run(
        prepare(run, payload, records, StyleEvidenceInvalid("correction limit"))
    )
    assert len(plans) == 2 and run.state() == original and analysis == original_analysis
    write_json(run.root / "context.json", run.context)
    snapshot = asyncio.run(run.snapshot())
    calls = []

    async def forbidden(*args):
        raise AssertionError("No additional AI analysis is authorized by fallback")

    async def edit(request):
        calls.append(request)
        if unknown:
            raise RuntimeError("Connection lost after dispatch")
        return result((768, 1024))

    gateway = SimpleNamespace(
        plan=forbidden,
        edit=edit,
        provider_name="synthetic",
        image_model="synthetic",
        pricing_version="test",
    )
    provider = ReplicaDeliveryProvider(
        lambda: nullcontext(SimpleNamespace(get=lambda *a: None)), gateway, run.storage
    )
    saved = []

    async def save(current, *args, **kwargs):
        saved.append(await current.snapshot())

    provider._save = save
    req = SimpleNamespace(
        job_id="job_style",
        workspace_id="ws_test",
        job_item_id="item_style",
        attempt_id="attempt_style",
    )
    values = {"replication_method": "style", "native_snapshot": snapshot}
    response = asyncio.run(execute(provider, req, values, run.document_id, 0))
    if unknown:
        assert response.outcome == "outcome_unknown", response.raw_usage
        assert not response.usage_reported and response.actual_cost_micros is None
        values["native_executions"] = {"job_style": {"snapshot": saved[-1]}}
        repeated = asyncio.run(execute(provider, req, values, run.document_id, 0))
        assert repeated.outcome == "outcome_unknown"
        assert len(calls) == 1  # The immediate failure stops still-waiting screens.
        return
    assert response.outcome == "succeeded", response.raw_usage
    assert len(calls) == 2
    assert all(
        {s.source_role for s in call.sources} <= {"product_reference", "format_canvas"}
        for call in calls
    )
    assert all(call.sources[0].sha256 == records["product"][2] for call in calls)
    assert read_json(run.root / STATE)["state"] == "DELIVERED"
    values["native_executions"] = {"job_style": {"snapshot": saved[-1]}}
    assert (
        asyncio.run(execute(provider, req, values, run.document_id, 1)).outcome
        == "succeeded"
    )
    assert len(calls) == 2


def test_failed_plan_remains_failed_evidence_but_has_executable_completion(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_always = True
    with pytest.raises(ReplicaPlanAuditRejected) as failed:
        asyncio.run(run.prepare(payload, records))
    original = deepcopy(run.state())
    before = len(gateway.requests)
    plans = asyncio.run(prepare(run, payload, records, failed.value))
    assert len(plans) == 2 and len(gateway.requests) == before
    assert run.state() == original and original["state"] == "PLAN_REJECTED"
    completion = read_json(run.root / PLAN)
    assert completion["planning_status"] == "BEST_EFFORT"
    assert any(
        a["decision"] == "FAIL" for a in completion["last_judgment"]["unit_audits"]
    )
    assert read_json(run.root / STATE)["review_status"] == "NOT_REVIEWED"


def test_changed_original_cannot_be_hidden_by_best_effort(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_always = True
    with pytest.raises(ReplicaPlanAuditRejected) as failed:
        asyncio.run(run.prepare(payload, records))
    product = Path(run.context["product_paths"][0])
    product.write_bytes(b"changed original")
    with pytest.raises(ReplicaNativeError, match="哈希"):
        asyncio.run(prepare(run, payload, records, failed.value))
    assert not (run.root / PLAN).exists()


def test_issued_image_cannot_be_replaced_by_analysis_completion(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_always = True
    with pytest.raises(ReplicaPlanAuditRejected) as failed:
        asyncio.run(run.prepare(payload, records))
    write_json(run.root / "invocations.json", {"issued": {"state": "invoked"}})
    with pytest.raises(ReplicaNativeError, match="已有生图请求"):
        asyncio.run(prepare(run, payload, records, failed.value))


def test_completion_rejects_cross_workspace_object_before_restore(tmp_path):
    from app.replica_completion import CompletionRun

    run, gateway, _, _ = setup_run(tmp_path)
    snapshot = asyncio.run(run.snapshot())
    snapshot["files"]["forged.img"] = {
        "object_key": "other-workspace/replica/other-document/pixels.img",
        "sha256": "0" * 64,
    }
    completion = CompletionRun(
        "exact", run.document_id, run.workspace_id, gateway, run.storage, root=run.root
    )
    completion.binding = snapshot.get("model_protocol")
    with pytest.raises(ReplicaNativeError, match="当前工作区"):
        asyncio.run(completion.restore(snapshot))


def test_http_bounded_failure_creates_one_job_and_delivers_without_extra_click(
    client, tmp_path, monkeypatch
):
    settings = client.app.state.settings
    settings.reference_remix_provider_enabled = True
    settings.replica_exact_compact_workspaces = ("ws_test",)
    gateway = SyntheticGateway()
    gateway.reject_always = True
    original_edit = gateway.edit
    image_started = 0
    observed_streaming = []

    async def out_of_order_edit(request):
        nonlocal image_started
        image_started += 1
        if image_started == 1:
            # Hold the first screen until the second is a real downloadable
            # output while the job remains active, not a progress placeholder.
            for _ in range(500):
                with client.app.state.session_factory() as db:
                    link = db.scalar(
                        select(JobAssetRecord).where(
                            JobAssetRecord.direction == "output",
                            JobAssetRecord.ordinal == 1,
                        )
                    )
                    if link is not None:
                        asset = db.get(AssetRecord, link.asset_id)
                        data = await client.app.state.storage.read_bytes(
                            asset.object_key
                        )
                        assert (
                            data
                            and db.get(JobRecord, link.job_id).status == "processing"
                        )
                        observed_streaming.append(link.ordinal)
                        break
                await asyncio.sleep(0.01)
            assert observed_streaming, (
                "second screen was held until all images finished"
            )
        return await original_edit(request)

    gateway.edit = out_of_order_edit
    client.app.state.replica_gateway = gateway
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        reference_remix_provider_enabled=True,
        aurora_work_root=tmp_path / "worker",
    )
    original_init = CompactExactReplicaRun.__init__

    def isolated_init(self, *args, **kwargs):
        kwargs.setdefault("root", tmp_path / "native")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(CompactExactReplicaRun, "__init__", isolated_init)
    ids = []
    for i, size in enumerate([(64, 96), (256, 640)]):
        out = BytesIO()
        Image.new("RGB", size, "blue" if i == 0 else "yellow").save(out, "PNG")
        response = client.post(
            "/api/v1/workspaces/ws_test/assets",
            headers={"Idempotency-Key": uuid4().hex},
            files={"file": ("test.png", out.getvalue(), "image/png")},
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    route = "/api/v1/workspaces/ws_test/replica"
    response = client.post(
        route + "/sessions",
        json={
            "request_id": uuid4().hex,
            "replication_method": "exact",
            "product_asset_ids": ids[:1],
            "references": [{"asset_id": ids[1]}],
            "facts": "Supported synthetic product",
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202
    did = response.json()["id"]
    doc = client.get(route + "/documents/" + did).json()
    assert doc["status"] == "generating", doc
    assert doc["payload"]["planning_status"] == "BEST_EFFORT"
    assert len(doc["payload"]["job_ids"]) == 1
    with client.app.state.session_factory() as db:
        stored = db.get(ReplicaDocumentRecord, did).payload
        assert len(stored["_analysis_lineage"]) == 1
        assert (
            document_file(stored["_analysis_lineage"][0], "session.json")["state"]
            == "PLAN_REJECTED"
        )
        root = Path(stored["native_snapshot"]["root"])
    # A process restart must recover the best-effort plan, not start analysis.
    rmtree(root)
    before = len(gateway.requests)
    dispatch_pending(client)
    jid = doc["payload"]["job_ids"][0]
    job = client.get("/api/v1/workspaces/ws_test/jobs/" + jid).json()
    assert job["status"] == "completed", job
    assert job["succeeded_item_count"] == 2 and len(gateway.image_requests) == 2
    assert observed_streaming == [1]
    outputs = [a for a in job["assets"] if a["direction"] == "output"]
    assert sorted(a["ordinal"] for a in outputs) == [0, 1]
    with client.app.state.session_factory() as db:
        # Settlement reuses streamed assets; it does not create duplicates.
        assert (
            len(
                db.scalars(
                    select(AssetRecord).where(AssetRecord.origin_kind == "generated")
                ).all()
            )
            == 2
        )
    assert len(gateway.requests) == before
    assert client.get(route + "/documents/" + did).json()["status"] == "completed"
    with client.app.state.session_factory() as db:
        assert len(db.scalars(select(JobRecord)).all()) == 1
    asyncio.run(client.app.state.task_runner.run(jid))
    assert len(gateway.image_requests) == 2
    record = next(x for x in client.get(route + "/records").json() if x["id"] == did)
    assert record["status"] == "completed" and record["job_ids"] == [jid]
