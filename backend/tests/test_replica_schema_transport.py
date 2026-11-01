"""Exercise the refined crop gate through an object-root-only planner relay."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.replica_refined import bundle
from app.xinghe_agent import TengliOpenAICompatibleGateway, _planner_response_format

from .test_replica_modes import refined_suite


def routed_crop_review(monkeypatch, tmp_path, *, invalid=None, primary_failure=False):
    module = bundle("replica_crop_integrity")
    original = module._review
    calls = []
    verdict = {}

    async def post_json(**kwargs):
        calls.append(deepcopy(kwargs))
        body = kwargs["payload"]
        schema = body["response_format"]["json_schema"]["schema"]
        if "allOf" in schema:
            return 400, {"error": {"message": "Invalid schema: top-level allOf"}}
        if primary_failure and len(calls) == 1:
            return 502, {"error": {"message": "Synthetic upstream failure"}}
        return 200, {
            "id": "synthetic-crop-review",
            "choices": [{"message": {"content": json.dumps(verdict)}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 17},
        }

    gateway = TengliOpenAICompatibleGateway(
        api_key="synthetic-primary",
        base_url="https://primary.invalid",
        planner_model="synthetic-planner",
        image_model="synthetic-image",
        transport=SimpleNamespace(post_json=post_json),
        failover_enabled=True,
        failover_api_key="synthetic-backup",
        failover_base_url="https://backup.invalid",
        failover_model="synthetic-planner",
        planner_recovery_enabled=True,
        planner_retry_backoff_seconds=0,
        planner_receipt_root=tmp_path / "transport",
    )

    async def review(run, column, proposal, paths):
        verdict.clear()
        verdict.update(
            column_id=column["column_id"],
            screen_count=len(proposal["screens"]),
            decision="PASS",
            boundary_ys=list(proposal["boundary_ys"]),
            evidence="Synthetic source panels retain their complete copy and carriers.",
            **{name: True for name in module.CHECKS},
        )
        if invalid in module.CHECKS:
            verdict[invalid] = False
        elif invalid == "changed_pass_boundaries":
            verdict["boundary_ys"][0] += 1
        elif invalid == "revise_without_incomplete_content":
            verdict["decision"] = "REVISE"
        previous = run.gateway
        run.gateway = gateway
        try:
            return await original(run, column, proposal, paths)
        finally:
            run.gateway = previous

    monkeypatch.setattr(module, "_review", review)
    return calls


@pytest.mark.parametrize("primary_failure", [False, True])
def test_refined_crop_gate_crosses_relay_and_retains_planner_fallback(
    client, monkeypatch, tmp_path, primary_failure
):
    calls = routed_crop_review(
        monkeypatch, tmp_path, primary_failure=primary_failure
    )
    doc, gateway, _ = refined_suite(client)
    assert doc["status"] == "generating", doc["payload"].get("error")
    assert doc["payload"]["job_ids"] and not gateway.image_requests
    assert calls[0]["url"].startswith("https://primary.invalid/")
    if primary_failure:
        assert calls[1]["url"].startswith("https://backup.invalid/")
    else:
        assert len(calls) == 1
    for call in calls:
        body = call["payload"]
        wire_schema = body["response_format"]["json_schema"]["schema"]
        assert wire_schema["type"] == "object" and "allOf" not in wire_schema
        assert wire_schema["additionalProperties"] is False
        assert set(wire_schema["required"]) == set(wire_schema["properties"])
        prompt = body["messages"][1]["content"][0]["text"]
        assert '"allOf"' in prompt and '"anyOf"' in prompt


@pytest.mark.parametrize(
    "invalid",
    [
        "headlines_attached",
        "dependent_copy_complete",
        "visual_carriers_complete",
        "changed_pass_boundaries",
        "revise_without_incomplete_content",
    ],
)
def test_relay_compatible_crop_reply_still_must_pass_full_local_schema(
    client, monkeypatch, tmp_path, invalid
):
    calls = routed_crop_review(monkeypatch, tmp_path, invalid=invalid)
    doc, gateway, _ = refined_suite(client)
    assert doc["status"] == "failed"
    assert "Physical source crop response failed its complete schema" in (
        doc["payload"]["error"]
    )
    assert len(calls) == 2  # One format correction; invalid content never passes.
    assert not doc["payload"].get("job_ids") and not gateway.image_requests


def test_transport_adaptation_does_not_mutate_full_or_nested_schema():
    full = bundle("replica_crop_integrity").review_schema("C001", 2, [500])
    full["properties"]["evidence"]["allOf"] = [{"minLength": 30}]
    before = deepcopy(full)
    request = SimpleNamespace(
        planning_profile="replica_exact_compact",
        product_information=(json.dumps({"response_schema": full}),),
    )
    wire = _planner_response_format(request)["json_schema"]["schema"]
    assert wire == {key: value for key, value in before.items() if key != "allOf"}
    assert full == before and "allOf" in json.loads(request.product_information[0])[
        "response_schema"
    ]
    assert wire["properties"]["evidence"]["allOf"] == [{"minLength": 30}]


def test_existing_schema_rejection_resumes_once_and_preserves_original_receipt(
    client, monkeypatch, tmp_path
):
    from app import planner_recovery, xinghe_agent

    from .test_replica_fast import ROUTE

    calls = routed_crop_review(monkeypatch, tmp_path)
    compatible = xinghe_agent._planner_response_format
    corrected_request = planner_recovery.object_root_request

    def old_format(request):
        if request.planning_profile == "replica_exact_compact":
            return {"type": "json_schema", "json_schema": {
                "name": "replica_exact_compact", "strict": False,
                "schema": json.loads(request.product_information[0])["response_schema"],
            }}
        return compatible(request)

    monkeypatch.setattr(xinghe_agent, "_planner_response_format", old_format)
    monkeypatch.setattr(planner_recovery, "object_root_request", lambda _, req: req)
    failed, _, _ = refined_suite(client)
    assert failed["status"] == "failed" and len(calls) == 1
    receipts = {p: p.read_bytes() for p in (tmp_path / "transport").rglob("*.json")}
    assert len(receipts) == 1
    assert all(
        json.loads(raw)["result"]["http_status"] == 400 for raw in receipts.values()
    )
    monkeypatch.setattr(xinghe_agent, "_planner_response_format", compatible)
    monkeypatch.setattr(planner_recovery, "object_root_request", corrected_request)
    response = client.post(ROUTE + f"/sessions/{failed['id']}/retry")
    assert response.status_code == 202, response.text
    recovered = client.get(ROUTE + "/documents/" + failed["id"]).json()
    assert recovered["status"] == "generating", recovered["payload"].get("error")
    assert len(calls) == 2
    assert all(p.read_bytes() == raw for p, raw in receipts.items())
    assert len(list((tmp_path / "transport").rglob("*.json"))) == 2


def constrained_request():
    from dataclasses import replace

    from .test_planner_stream_recovery import request

    return replace(
        request(),
        planning_profile="replica_exact_compact",
        product_information=(json.dumps({"response_schema": {
            "type": "object", "properties": {"accepted": {"type": "boolean"}},
            "allOf": [{"properties": {"accepted": {"const": True}}}],
        }}),),
    )


@pytest.mark.parametrize("outcome", ["success", "http_502", "stream_unknown"])
def test_schema_adaptation_reuses_success_and_never_reopens_unknown_calls(
    tmp_path, outcome
):
    import asyncio

    from app.planner_recovery import recover

    from .test_planner_stream_recovery import Transport, adapter

    transport = Transport(
        statuses=(502,) if outcome == "http_502" else (200,),
        cut_first=outcome == "stream_unknown",
    )
    gateway = adapter(transport, tmp_path, keys="")
    gateway.planner_transient_retries = 0
    request = constrained_request()
    first = asyncio.run(recover(gateway, request))  # A pre-adaptation receipt.
    receipts = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    replayed = asyncio.run(gateway.plan(request))
    assert replayed.payload == first.payload
    assert replayed.error_code == first.error_code
    assert not replayed.external_request and len(transport.calls) == 1
    assert all(p.read_bytes() == raw for p, raw in receipts.items())


def test_rejected_corrected_format_is_replayed_without_another_paid_request(tmp_path):
    import asyncio

    from .test_planner_stream_recovery import Transport, adapter

    transport = Transport(statuses=(400,))
    gateway = adapter(transport, tmp_path, keys="")
    request = constrained_request()
    first = asyncio.run(gateway.plan(request))
    replayed = asyncio.run(gateway.plan(request))
    assert first.http_status == replayed.http_status == 400
    assert len(transport.calls) == 1 and not replayed.external_request


@pytest.mark.parametrize("state", ["unfinished", "locked", "corrupt"])
def test_schema_correction_cannot_bypass_incomplete_or_invalid_receipts(
    tmp_path, state
):
    import asyncio

    from app.planner_recovery import Journal, _route, recover

    from .test_planner_stream_recovery import Transport, adapter

    transport = Transport(statuses=(400,))
    gateway = adapter(transport, tmp_path, keys="")
    request = constrained_request()
    routes = [_route(gateway, route) for route in gateway._ordered_routes()]
    journal = Journal(tmp_path, request, routes)
    if state == "corrupt":
        asyncio.run(recover(gateway, request))
        value = json.loads(journal.path.read_bytes())
        value["result"]["error_message"] = "Changed original receipt"
        journal.path.write_text(json.dumps(value), encoding="utf-8")
    else:
        journal.enter()
        journal.begin(routes[0], 1)
        if state == "unfinished":
            journal.close()
    before = len(transport.calls)
    try:
        result = asyncio.run(gateway.plan(request))
    finally:
        journal.close()
    expected = (
        "PLANNER_RECOVERY_IN_PROGRESS" if state == "locked"
        else "PLANNER_RECOVERY_RECEIPT_INVALID"
    )
    assert result.error_code == expected and not result.external_request
    assert len(transport.calls) == before
