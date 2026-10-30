"""Real SSE framing, bounded failover and recovery evidence; no paid calls."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import asdict, replace
from io import BytesIO

import pytest

from app import detail_fast, refined_detail
from app.domestic_detail.planner_dispatch import (
    NATIVE_PLANNER_PROFILES,
    PlannerDispatchError,
    validate_dispatch_result,
)
from app.planner_recovery import Journal, _route, digest, summary
from app.planner_streaming import PlannerStreamError, read_chat_stream
from app.xinghe_agent import (
    TengliOpenAICompatibleGateway,
    UrllibOpenAITransport,
    XingheAgentError,
    _fake_plan,
    _planner_call_results,
)
from tests.test_detail_fast_contract import request


def sse(content='{"accepted":"合成"}', *, done=True, finish="stop", usage=True):
    pieces = [content[:7], content[7:]]
    frames = [b": keepalive\r\n\r\n"]
    for piece in pieces:
        frames.append(
            (
                "data: "
                + json.dumps(
                    {
                        "id": "synthetic-stream",
                        "model": "test-model",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": piece},
                                "finish_reason": None,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\r\n\r\n"
            ).encode()
        )
    if finish is not None:
        frames.append(
            (
                "data: "
                + json.dumps(
                    {
                        "id": "synthetic-stream",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    }
                )
                + "\n\n"
            ).encode()
        )
    if usage:
        frames.append(
            b'data: {"choices":[],"usage":{"prompt_tokens":9,'
            b'"completion_tokens":7,"total_tokens":16}}\n\n'
        )
    if done:
        frames.append(b"data: [DONE]\n\n")
    return b"".join(frames)


class Transport:
    def __init__(
        self, statuses=(502, 200), content='{"accepted":true}', cut_first=False
    ):
        self.statuses = statuses
        self.content = content
        self.cut_first = cut_first
        self.calls = []

    async def post_json(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        index = len(self.calls) - 1
        status = self.statuses[min(index, len(self.statuses) - 1)]
        if status >= 400:
            return status, {
                "error": {
                    "type": "upstream_error",
                    "message": "Synthetic upstream failure",
                }
            }
        raw = sse(self.content, done=not (self.cut_first and index == 0))
        try:
            return 200, read_chat_stream(BytesIO(raw), 20)
        except PlannerStreamError as exc:
            error = XingheAgentError(exc.code, str(exc), retryable=True)
            error.planner_response = exc.envelope
            raise error from exc


def adapter(transport, root=None, keys="backup-one"):
    return TengliOpenAICompatibleGateway(
        api_key="offline-primary",
        base_url="https://primary.offline.invalid",
        planner_model="test-model",
        image_model="synthetic-image",
        transport=transport,
        failover_enabled=bool(keys),
        failover_api_key=keys,
        failover_base_url="https://backup.offline.invalid",
        failover_model="test-model",
        planner_streaming_enabled=True,
        planner_recovery_enabled=True,
        planner_transient_retries=1,
        planner_retry_backoff_seconds=0,
        planner_receipt_root=root,
    )


def test_sse_unicode_usage_and_terminal_choice_are_reassembled():
    value = read_chat_stream(BytesIO(sse()), 20)
    assert json.loads(value["choices"][0]["message"]["content"]) == {"accepted": "合成"}
    assert value["usage"]["total_tokens"] == 16
    assert value["_planner_stream"]["complete"] is True


@pytest.mark.parametrize("done,finish", [(False, "stop"), (True, None), (False, None)])
def test_valid_json_without_full_stream_completion_never_succeeds(done, finish):
    with pytest.raises(PlannerStreamError) as caught:
        read_chat_stream(BytesIO(sse(done=done, finish=finish)), 20)
    assert caught.value.code == "PLANNER_STREAM_INTERRUPTED"
    assert caught.value.envelope["_planner_stream"]["complete"] is False


def test_stream_error_event_does_not_return_a_partial_plan():
    raw = (
        sse(done=False, finish=None, usage=False)
        + b'data: {"error":{"message":"synthetic"}}\n\n'
    )
    with pytest.raises(PlannerStreamError, match="did not finish") as caught:
        read_chat_stream(BytesIO(raw), 20)
    assert caught.value.code == "PLANNER_STREAM_ERROR"
    assert caught.value.envelope["error"]["message"] == "synthetic"


def test_urllib_transport_reads_sse_instead_of_parsing_the_whole_wire_as_json(
    monkeypatch,
):
    class Response(BytesIO):
        status = 200
        headers = {"Content-Type": "text/event-stream; charset=utf-8"}

    monkeypatch.setattr(
        UrllibOpenAITransport, "_open", staticmethod(lambda *_: Response(sse()))
    )
    status, payload = asyncio.run(
        UrllibOpenAITransport().post_json(
            url="https://offline.invalid/v1/chat/completions",
            headers={},
            payload={"stream": True},
            timeout_seconds=10,
        )
    )
    assert status == 200 and payload["_planner_stream"]["complete"] is True


PROFILES = sorted(
    (
        NATIVE_PLANNER_PROFILES
        - {"aurora_detail_campaign_audit", "aurora_detail_revision_scope"}
    )
    | {
        "detail_pack",
        "crossborder_detail",
        detail_fast.PROFILE,
        refined_detail.PROFILE,
        "amazon_visual_suite_fast",
        "amazon_visual_suite",
        "replica_fast_suite",
        "aurora_native_fast_identity",
        "aurora_identity",
        "replica_exact_compact",
        "replica_native_contract",
        "reference_visual_remix",
        "creative_image",
        "aurora_remix_fast_prepare",
        "aurora_remix_fast_review",
        "aurora_v20_visual_audit",
    }
)


@pytest.mark.parametrize(
    "profile", ["aurora_detail_campaign_audit", "aurora_detail_revision_scope"]
)
def test_missing_review_or_revision_contract_stops_before_any_paid_call(profile):
    transport = Transport()
    gateway = adapter(transport)
    result = asyncio.run(gateway.plan(replace(request(), planning_profile=profile)))
    assert result.error_code is not None
    assert not transport.calls


@pytest.mark.parametrize("profile", PROFILES)
def test_all_platform_planning_profiles_stream_and_fall_back(profile, tmp_path):
    transport = Transport()
    gateway = adapter(transport, tmp_path)
    req = replace(
        request(),
        planning_profile=profile,
        product_information=(json.dumps({"response_schema": {"type": "object"}}),),
    )
    if profile in NATIVE_PLANNER_PROFILES:
        req = replace(req, native_dispatch=gateway.native_planner_route())
    result = asyncio.run(gateway.plan(req))
    assert result.error_code is None, (profile, result.error_code, result.error_message)
    assert result.payload == {"accepted": True}
    assert gateway.external_network_request_count == len(transport.calls) == 2
    assert [call["url"].split("/")[2] for call in transport.calls] == [
        "primary.offline.invalid",
        "backup.offline.invalid",
    ]
    assert all(call["payload"]["stream"] is True for call in transport.calls)
    assert all(
        call["payload"]["stream_options"] == {"include_usage": True}
        for call in transport.calls
    )
    assert len(_planner_call_results([result])) == 2
    assert result.supplemental_results[0].http_status == 502
    proof = summary(result)
    assert proof["attempts"][0]["raw_usage"] is None
    assert proof["attempts"][1]["raw_usage"]["total_tokens"] == 16
    assert "offline-primary" not in json.dumps(proof)
    assert "backup-one" not in json.dumps(proof)
    if profile in NATIVE_PLANNER_PROFILES:
        validate_dispatch_result(asdict(result), req.native_dispatch)


def test_native_chain_cannot_substitute_a_different_dispatch_or_payload():
    gateway = adapter(Transport())
    req = replace(request(), planning_profile="aurora_domestic_detail")
    result = asyncio.run(gateway.plan(req))
    assert result.error_code is None
    bound = gateway.native_planner_route()
    value = asdict(result)
    validate_dispatch_result(value, bound)
    value["payload"] = {"forged": True}
    with pytest.raises(PlannerDispatchError):
        validate_dispatch_result(value, bound)


def test_native_durable_store_round_trips_all_fallback_receipts(tmp_path):
    from app.domestic_detail.planning_calls import NativePlanningStore, call_binding

    gateway = adapter(Transport())
    req = replace(request(), planning_profile="aurora_domestic_detail")
    result = asyncio.run(gateway.plan(req))
    assert result.error_code is None
    binding = call_binding(
        profile=req.planning_profile,
        group_key=req.group_key,
        target="synthetic",
        logical_key=req.idempotency_key,
        semantics={},
        prompt="synthetic",
        schema={"type": "object"},
        route=gateway.native_planner_route(),
        skill_hash="synthetic",
        runtime_hash="synthetic",
    )
    store = NativePlanningStore(tmp_path, binding)
    store.begin()
    saved = store.finish(asdict(result))
    from app.xinghe_agent import PlannerCallResult

    restored = PlannerCallResult(**saved)
    assert len(_planner_call_results([restored])) == 2
    validate_dispatch_result(asdict(restored), gateway.native_planner_route())
    assert store.completed()["payload"] == result.payload
    value = asdict(result)
    proof = value["provider_envelope"]["planner_recovery"]
    proof["attempts"][0]["dispatch"]["transport_attempts"] = 2
    proof["sha256"] = digest({k: v for k, v in proof.items() if k != "sha256"})
    with pytest.raises(PlannerDispatchError):
        validate_dispatch_result(value, gateway.native_planner_route())


def test_interrupted_stream_uses_backup_and_keeps_partial_call_receipt(tmp_path):
    transport = Transport(statuses=(200, 200), cut_first=True)
    gateway = adapter(transport, tmp_path)
    result = asyncio.run(gateway.plan(request()))
    assert result.error_code is None and len(transport.calls) == 2
    assert result.supplemental_results[0].error_code == "PLANNER_STREAM_INTERRUPTED"
    assert (
        result.supplemental_results[0].provider_envelope["planner_stream"]["complete"]
        is False
    )
    state = json.loads(next(tmp_path.rglob("*.json")).read_bytes())
    assert len(state["calls"]) == 2 and all(
        call["state"] == "returned" for call in state["calls"]
    )


@pytest.mark.parametrize("status,expected", [(503, 5), (401, 4), (400, 1)])
def test_failed_route_pool_has_a_global_attempt_ceiling(status, expected):
    transport = Transport(statuses=(status,))
    gateway = adapter(transport, keys="one,two,three")
    result = asyncio.run(gateway.plan(request()))
    assert result.error_code is not None
    assert gateway.external_network_request_count == len(transport.calls) == expected
    assert len(_planner_call_results([result])) == expected


def test_duplicate_dispatch_replays_durable_result_without_another_post(tmp_path):
    transport = Transport()
    gateway = adapter(transport, tmp_path)
    first = asyncio.run(gateway.plan(request()))
    second = asyncio.run(gateway.plan(request()))
    assert first.payload == second.payload and second.error_code is None
    assert len(transport.calls) == 2 and not second.external_request
    assert not _planner_call_results([second])


def test_crash_marker_and_changed_inputs_block_new_calls(tmp_path):
    transport = Transport()
    gateway = adapter(transport, tmp_path)
    routes = [_route(gateway, route) for route in gateway._ordered_routes()]
    journal = Journal(tmp_path, request(), routes)
    journal.enter()
    journal.begin(routes[0], 1)
    journal.close()
    result = asyncio.run(gateway.plan(request()))
    assert result.error_code == "PLANNER_RECOVERY_RECEIPT_INVALID"
    changed = asyncio.run(gateway.plan(replace(request(), page_count=6)))
    assert changed.error_code == "PLANNER_RECOVERY_RECEIPT_INVALID"
    assert not transport.calls


def test_full_site_fast_plan_retains_failed_and_successful_usage_before_generation(
    client, monkeypatch, tmp_path
):
    from tests.test_api import dispatch_pending, idem, upload_asset
    from tests.test_detail_fast_integration import BASE, request_payload
    from tests.test_domestic_detail_execution import _gateway

    fake = _gateway(client)
    transport = Transport()
    routed = adapter(transport, tmp_path)

    async def plan(req):
        transport.content = json.dumps(_fake_plan(req), ensure_ascii=False)
        return await routed.plan(req)

    monkeypatch.setattr(fake, "plan", plan)
    source = upload_asset(client)
    created = client.post(
        BASE + "/jobs", headers=idem(), json=request_payload(source["id"], 8)
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    dispatch_pending(client)
    job = client.get(BASE + f"/jobs/{job_id}").json()
    assert job["status"] == "awaiting_confirmation", job
    usage = job["plan"]["payload"]["usage"]["planner"]
    assert len(usage) == 2
    assert sorted(row["http_status"] for row in usage) == [200, 502]
    assert fake.image_calls == []
    assert len(transport.calls) == 2
    dispatch_pending(client)
    assert len(transport.calls) == 2
