"""Runtime budget removal and real HTTP/worker checkpoint continuation."""

import asyncio
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import pytest
from PIL import Image

from app.replica_exact_compact import CompactExactReplicaRun, run_class
from app.replica_execution_resume import (
    V3_BINDING,
    restore_execution,
    validate_checkpoint,
)
from app.replica_native import ReplicaNativeError
from app.replica_native_provider import NativeReplicaProvider
from tests.test_replica_compact import SyntheticGateway, setup_run


def interrupted_run(tmp_path):
    prepared, gateway, payload, records = setup_run(tmp_path)
    legacy_type = run_class("exact", V3_BINDING)
    run = legacy_type(
        "exact",
        prepared.document_id,
        prepared.workspace_id,
        gateway,
        prepared.storage,
        root=tmp_path,
    )
    assert run.binding == V3_BINDING
    asyncio.run(run.prepare(payload, records))
    baseline = deepcopy(asyncio.run(run.snapshot()))
    run.usage.append({"kind": "analysis", "network_requests": 10000})
    provider = NativeReplicaProvider(None, gateway, run.storage)

    async def save(*args, **kwargs):
        pass

    provider._save = save
    from types import SimpleNamespace

    request = SimpleNamespace(
        workspace_id="ws_test",
        job_id="job_old",
        job_item_id="item_old",
        attempt_id="attempt_old",
    )
    module = __import__(
        legacy_type.__module__, fromlist=["CompactAnalysisBudgetExceeded"]
    )
    with pytest.raises(module.CompactAnalysisBudgetExceeded):
        asyncio.run(provider._exact(run, request))
    assert len(gateway.image_requests) == 1
    assert run.state()["state"] == "AWAITING_AUDIT"
    return run, gateway, provider, request, baseline


def test_large_historical_usage_continues_same_artwork_without_budget_or_replanning(
    tmp_path,
):
    old, gateway, provider, request, baseline = interrupted_run(tmp_path)
    snapshot = asyncio.run(old.snapshot())
    validate_checkpoint(
        snapshot, baseline, f"{old.workspace_id}/replica/{old.document_id}/"
    )
    original_artwork = old.state()["modules"][0]["attempts"][-1]["artwork"]
    original_record = deepcopy(
        snapshot["files"][Path(original_artwork).relative_to(old.root).as_posix()]
    )
    before = len(gateway.requests)
    run = CompactExactReplicaRun(
        "exact", old.document_id, old.workspace_id, gateway, old.storage, root=tmp_path
    )
    asyncio.run(restore_execution(run, snapshot, "job_old"))
    request.job_id = "job_retry"
    outputs = asyncio.run(provider._exact(run, request))
    assert run.state()["state"] == "FINALIZED" and len(outputs) == 2
    assert outputs[0] == original_artwork
    assert len(gateway.image_requests) == 2  # Only the unfinished second image is new.
    assert len(gateway.requests) == before + 2  # Two actual pixel reviews, no planning.
    assert all(r.planning_deadline is None for r in gateway.requests[before:])
    fresh = asyncio.run(run.snapshot())
    assert (
        fresh["files"][Path(original_artwork).relative_to(old.root).as_posix()]
        == original_record
    )
    assert run.checkpoints["execution_resume"]["source_protocol"] == V3_BINDING
    assert all(
        m["attempts"][-1]["judgment"]["derived_decision"] == "PASS"
        for m in run.state()["modules"]
    )


@pytest.mark.parametrize("bad", ["context", "plan", "pixels", "judgment", "order"])
def test_resume_refuses_changed_source_or_a_verdict_it_would_ignore(tmp_path, bad):
    old, _, _, _, baseline = interrupted_run(tmp_path)
    snapshot = asyncio.run(old.snapshot())
    name = "context.json" if bad == "context" else "session.json"
    value = json.loads(snapshot["files"][name]["text"])
    if bad == "context":
        value["user_facts"] = "Changed facts"
    elif bad == "plan":
        value["plan"]["modules"][0]["generation_brief"] += " Changed."
    elif bad == "judgment":
        value["modules"][0]["attempts"][-1]["judgment"] = {"derived_decision": "FAIL"}
    elif bad == "order":
        value["modules"][1]["status"] = "COMPLETE"
    else:
        image = next(k for k, r in baseline["files"].items() if "object_key" in r)
        snapshot["files"][image]["sha256"] = "0" * 64
    if bad != "pixels":
        from tests.test_replica_retry import json_record

        snapshot["files"][name] = json_record(value)
    with pytest.raises(ReplicaNativeError):
        validate_checkpoint(
            snapshot, baseline, f"{old.workspace_id}/replica/{old.document_id}/"
        )


def test_http_retry_restores_durable_partial_run_and_keeps_actual_pass(
    client, monkeypatch, tmp_path
):
    from app import replica_exact_compact
    from app.models import ReplicaDocumentRecord
    from app.task_runner import MockTaskRunner
    from tests.test_api import dispatch_pending

    settings = client.app.state.settings
    settings.reference_remix_provider_enabled = True
    settings.replica_exact_compact_workspaces = ("ws_test",)
    gateway = SyntheticGateway()
    client.app.state.replica_gateway = gateway
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        reference_remix_provider_enabled=True,
        aurora_work_root=tmp_path / "worker",
    )
    legacy = run_class("exact", V3_BINDING)
    original = legacy._visual_stage
    budget_type = __import__(
        legacy.__module__, fromlist=["CompactAnalysisBudgetExceeded"]
    ).CompactAnalysisBudgetExceeded

    async def interrupted(self, stage, context, **kwargs):
        module = context.get("data", context).get("module", {})
        if stage.startswith("exact-pixel-audit") and module.get("id") == "M002":
            raise budget_type()
        return await original(self, stage, context, **kwargs)

    monkeypatch.setattr(legacy, "_visual_stage", interrupted)
    for cls in (legacy, CompactExactReplicaRun):
        init = cls.__init__

        def isolated(self, *args, _init=init, **kwargs):
            kwargs.setdefault("root", tmp_path.parent / "n")
            _init(self, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", isolated)
    ids = []
    for i, size in enumerate([(64, 96), (256, 640)]):
        image = BytesIO()
        Image.new("RGB", size, "blue" if i == 0 else "yellow").save(image, "PNG")
        response = client.post(
            "/api/v1/workspaces/ws_test/assets",
            headers={"Idempotency-Key": str(uuid4())},
            files={"file": (f"source-{i}.png", image.getvalue(), "image/png")},
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    current_version = replica_exact_compact.VERSION
    monkeypatch.setattr(replica_exact_compact, "VERSION", "exact-compact-v3")
    route = "/api/v1/workspaces/ws_test/replica"
    response = client.post(
        route + "/sessions",
        json={
            "request_id": str(uuid4()),
            "replication_method": "exact",
            "product_asset_ids": ids[:1],
            "references": [{"asset_id": ids[1]}],
            "facts": "Supported synthetic product",
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["id"]
    document = client.get(route + "/documents/" + document_id).json()
    job_id = document["payload"]["job_ids"][0]
    dispatch_pending(client)
    failed = client.get(route + "/documents/" + document_id).json()
    assert (
        failed["status"] == "failed"
        and failed["payload"]["error_code"] == "REPLICA_ANALYSIS_BUDGET_REACHED"
    )
    assert len(gateway.image_requests) == 2
    with client.app.state.session_factory() as session:
        snapshot = deepcopy(
            session.get(ReplicaDocumentRecord, document_id).payload[
                "native_executions"
            ][job_id]["snapshot"]
        )
    state = json.loads(snapshot["files"]["session.json"]["text"])
    original_pass = deepcopy(state["modules"][0])
    assert state["state"] == "AWAITING_AUDIT" and state["module_index"] == 1
    root = Path(snapshot["root"]).resolve()
    assert root.is_relative_to(tmp_path.parent.resolve())
    rmtree(root)  # Actual new worker/API process must restore durable objects.
    monkeypatch.setattr(replica_exact_compact, "VERSION", current_version)
    before = len(gateway.requests)
    retry = client.post(
        route + f"/sessions/{document_id}/jobs/{job_id}/retry",
        json={"request_id": str(uuid4())},
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["payload"]["execution_progress"]["accepted"] == 1
    dispatch_pending(client)
    final = client.get(route + "/documents/" + document_id).json()
    assert final["status"] == "completed", final
    assert len(gateway.image_requests) == 2  # Both existing images survive.
    assert len(gateway.requests) == before + 1  # Only the pending review runs.
    new_id = final["payload"]["job_ids"][0]
    with client.app.state.session_factory() as session:
        values = session.get(ReplicaDocumentRecord, document_id).payload
        resumed = values["native_executions"][new_id]["snapshot"]
        final_state = json.loads(resumed["files"]["session.json"]["text"])
        assert final_state["modules"][0] == original_pass
        assert values["native_executions"][job_id]["snapshot"] == snapshot
        assert resumed["model_protocol"]["version"] == current_version
