"""Format variants at every fast-remix boundary, before any paid image call."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from app.provider import ProviderArtifact, ProviderOutcome
from app.remix_fast_brief import TEXT_FIELDS, BriefFormatError, normalize_brief
from app.remix_fast_contract import GEOMETRY_FIELDS, REFERENCE_FIELDS
from app.remix_fast_provider import _compile
from app.remix_fast_runtime import RemixFastRuntime
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem
from tests.test_remix_fast import _website_fast, brief, install
from tests.test_xinghe_single_image_provider import harness as harness

TEXT_PATHS = [(key,) for key in TEXT_FIELDS] + [
    (group, key)
    for group, keys in (
        ("geometry_lock", GEOMETRY_FIELDS),
        ("reference_facts", REFERENCE_FIELDS),
    )
    for key in keys
]


@pytest.mark.parametrize("path", TEXT_PATHS)
def test_string_lists_are_normalized_without_losing_statements(path):
    value = brief()
    target = value if len(path) == 1 else value[path[0]]
    target[path[-1]] = ['保持原图品牌 "A"', "保持横向纹样；不镜像"]
    original = deepcopy(value)
    fixed = normalize_brief(value)
    target = fixed if len(path) == 1 else fixed[path[0]]
    assert target[path[-1]] == '保持原图品牌 "A"\n保持横向纹样；不镜像'
    assert value == original


@pytest.mark.parametrize("path", TEXT_PATHS)
@pytest.mark.parametrize("invalid", [[], {}, None, 5, ["valid", 4], " ", "a" * 6001])
def test_missing_or_nontext_facts_are_not_silently_accepted(path, invalid):
    value = brief()
    target = value if len(path) == 1 else value[path[0]]
    target[path[-1]] = invalid
    with pytest.raises(BriefFormatError):
        normalize_brief(value)


@pytest.mark.parametrize(
    "wrapper", ["brief", "preparation", "result", "data", "output", "plan"]
)
def test_unambiguous_named_envelopes(wrapper):
    assert normalize_brief({wrapper: brief(), "usage": {"tokens": 1}}) == brief()


@pytest.mark.parametrize(
    "encode",
    [
        lambda v: json.dumps(v),
        lambda v: json.dumps(json.dumps(v)),
        lambda v: "```json\n" + json.dumps(v) + "\n```",
        lambda v: "\ufeff" + json.dumps(v),
        lambda v: {"data": json.dumps({"brief": v})},
    ],
)
def test_explicit_json_encoding_variants(encode):
    assert normalize_brief(encode(brief())) == brief()


def test_ambiguous_envelopes_are_rejected():
    with pytest.raises(BriefFormatError):
        normalize_brief({"brief": brief(), "result": brief()})


@pytest.mark.parametrize("literal", ["A,B / 20%", '包装上有 "A"', "第一行\n第二行"])
def test_literal_copy_is_never_guessed_into_separate_claims(literal):
    value = {**brief(), "approved_visible_copy": literal}
    assert normalize_brief(value)["approved_visible_copy"] == [literal]


def test_json_encoded_copy_array_and_empty_copy():
    for value in ([], ["A,B", "20%"], '["A,B", "20%"]'):
        result = normalize_brief({**brief(), "approved_visible_copy": value})
        assert result["approved_visible_copy"] == (
            json.loads(value) if isinstance(value, str) else value
        )


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("TRUE", True),
        (" false ", False),
        (1, True),
        (0, False),
    ],
)
def test_explicit_boolean_representations(value, expected):
    assert (
        normalize_brief({**brief(), "product_present": value})["product_present"]
        is expected
    )


@pytest.mark.parametrize("value", [None, "maybe", "not sure", 2, [], {}])
def test_unknown_visibility_is_not_inferred(value):
    with pytest.raises(BriefFormatError):
        normalize_brief({**brief(), "product_present": value})


@pytest.mark.parametrize("legacy", [None, [], "invalid crop", [{"box": [-1, 0, 9, 9]}]])
def test_removed_audit_regions_never_gate_generation(legacy):
    assert normalize_brief({**brief(), "critical_regions": legacy}) == brief()


def test_fully_flat_named_facts_can_be_relocated_without_inference():
    value = brief()
    value.update(value.pop("geometry_lock"))
    value.update(value.pop("reference_facts"))
    assert normalize_brief(value) == brief()


def test_schema_is_embedded_in_planning_prompt_and_matches_validation(
    harness, tmp_path
):
    provider, request = install(harness, tmp_path)
    asyncio.run(provider.execute(request))
    context = json.loads(harness.gateway.plan_requests[0].product_information[0])
    schema = context["response_schema"]
    Draft202012Validator(schema).validate(normalize_brief(brief()))
    assert "critical_regions" not in schema["properties"]
    assert "critical_regions" not in context["required_fields"]
    assert "CURRENT PRODUCT" in context["copy_authority"]
    assert "BENCHMARK" in context["copy_authority"]


@pytest.mark.parametrize(
    "initial_error", [None, "PLANNER_SCHEMA_INVALID", "PLANNER_OUTPUT_TRUNCATED"]
)
def test_one_format_repair_precedes_one_image_and_replay_adds_no_calls(
    harness, tmp_path, initial_error
):
    provider, request = install(harness, tmp_path)
    original = harness.gateway.plan

    async def plan(value):
        result = await original(value)
        if len(harness.gateway.plan_requests) == 1:
            payload = brief()
            payload.pop("reference_facts")
            return replace(
                result,
                payload=payload if initial_error is None else None,
                error_code=initial_error,
            )
        return result

    harness.gateway.plan = plan
    result = asyncio.run(provider.execute(request))
    assert result.outcome == ProviderOutcome.SUCCEEDED, result
    first, repair = harness.gateway.plan_requests
    assert first.idempotency_key != repair.idempotency_key
    assert first.sources == repair.sources
    assert "format_repair" in json.loads(repair.product_information[0])
    assert len(harness.gateway.requests) == 1
    assert [c["phase"] for c in result.raw_usage["calls"]] == [
        "prepare",
        "prepare_format_repair",
        "image",
    ]
    asyncio.run(provider.execute(request))
    assert len(harness.gateway.plan_requests) == 2
    assert len(harness.gateway.requests) == 1


def test_invalid_repair_is_bounded_and_never_authorizes_an_image(harness, tmp_path):
    provider, request = install(harness, tmp_path)
    original = harness.gateway.plan

    async def invalid(value):
        result = await original(value)
        return replace(result, payload={"product_present": True})

    harness.gateway.plan = invalid
    for _ in range(3):
        result = asyncio.run(provider.execute(request))
        assert result.error_code == "REMIX_FAST_PREPARATION_FAILED"
    assert len(harness.gateway.plan_requests) == 2
    assert harness.gateway.requests == []


def test_unknown_paid_outcome_after_format_repair_never_redraws(harness, tmp_path):
    provider, request = install(harness, tmp_path)
    original = harness.gateway.plan

    async def once(value):
        result = await original(value)
        return (
            replace(result, payload={})
            if len(harness.gateway.plan_requests) == 1
            else result
        )

    harness.gateway.plan = once
    harness.gateway.error = TimeoutError("response lost")
    for _ in range(2):
        assert (
            asyncio.run(provider.execute(request)).outcome
            == ProviderOutcome.OUTCOME_UNKNOWN
        )
    assert len(harness.gateway.plan_requests) == 2
    assert len(harness.gateway.requests) == 1


@pytest.mark.parametrize(
    "count,expected",
    [(None, 1), ("1", 1), ("invalid", 1), (-1, 1), (0, 0), (2, 2), (False, 1)],
)
def test_telemetry_format_cannot_fail_after_an_image_is_returned(
    harness, tmp_path, count, expected
):
    provider, request = install(harness, tmp_path)
    harness.gateway.result = replace(
        harness.gateway.result, raw_usage={"network_requests": count}
    )
    result = asyncio.run(provider.execute(request))
    assert result.outcome == ProviderOutcome.SUCCEEDED, result
    assert result.raw_usage["calls"][-1]["network_requests"] == expected


def test_planner_fallback_receipts_are_all_accounted(harness, tmp_path):
    provider, request = install(harness, tmp_path)
    original = harness.gateway.plan

    async def fallback(value):
        result = await original(value)
        failed = replace(
            result,
            payload=None,
            error_code="PLANNER_REQUEST_FAILED",
            actual_cost_micros=99,
        )
        return replace(result, supplemental_results=(failed,))

    harness.gateway.plan = fallback
    result = asyncio.run(provider.execute(request))
    assert result.raw_usage["request_count"] == 3
    assert result.actual_cost_micros == 321222


def test_reference_facts_compile_as_valid_json_with_quotes_newlines_and_backslashes():
    value = brief()
    for key in REFERENCE_FIELDS:
        value["reference_facts"][key] = '引号 "A"\n第二行 \\ 路径 <不替换>'
    prompt = _compile(RemixFastRuntime().prompt_template(), value, 1184, 1184)
    line = next(
        line for line in prompt.splitlines() if line.startswith("REFERENCE FACTS")
    )
    facts = json.loads(line[line.index("{") :])
    assert facts == value["reference_facts"]


@pytest.mark.parametrize(
    "image_format,mime",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
def test_native_provider_formats_are_delivered_byte_for_byte(
    harness, tmp_path, image_format, mime
):
    import hashlib

    provider, request = install(harness, tmp_path)
    stream = BytesIO()
    Image.new("RGB", (220, 300), "purple").save(stream, format=image_format)
    payload = stream.getvalue()
    artifact = ProviderArtifact(
        payload=payload,
        filename="candidate",
        content_type=mime,
        width=220,
        height=300,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    harness.gateway.result = replace(harness.gateway.result, artifact=artifact)
    result = asyncio.run(provider.execute(request))
    assert result.artifact.payload == payload
    assert result.artifact.content_type == mime
    assert result.raw_usage["metrics"]["post_generation_review"] == "disabled"


@pytest.mark.parametrize("count", [1, 2, 4])
def test_website_independent_image_counts_keep_planning_and_direct_delivery(
    client, tmp_path, count
):
    gateway, payload = _website_fast(client, tmp_path)
    payload["configuration"]["image_count"] = count
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs", headers=idem(), json=payload
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    dispatch_pending(client)
    job = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}").json()
    assert job["status"] == "completed", job
    assert len([a for a in job["assets"] if a["is_deliverable"]]) == count
    assert len(gateway.planner_calls) == len(gateway.image_calls) == count


@pytest.mark.parametrize(
    "kind,expected_plans",
    [
        ("plain", 1),
        ("fenced", 1),
        ("wrapper", 1),
        ("text_blocks", 1),
        ("relocated", 1),
        ("double_encoded", 1),
        ("bom", 1),
        ("malformed", 2),
        ("truncated", 2),
    ],
)
def test_real_gateway_transport_formats_reach_direct_delivery(
    harness, tmp_path, kind, expected_plans
):
    from app.xinghe_agent import TengliOpenAICompatibleGateway

    provider, request = install(harness, tmp_path)

    class Transport:
        def __init__(self):
            self.calls = []

        async def post_json(self, **kwargs):
            self.calls.append(kwargs)
            payload = brief()
            finish = "stop"
            if len(self.calls) == 1 and kind == "relocated":
                payload["typography_structure"] = payload["reference_facts"].pop(
                    "typography_structure"
                )
            content = json.dumps(payload, ensure_ascii=False)
            if len(self.calls) == 1:
                if kind == "fenced":
                    content = "```json\n" + content + "\n```"
                elif kind == "wrapper":
                    content = json.dumps({"brief": payload}, ensure_ascii=False)
                elif kind == "text_blocks":
                    content = [{"type": "text", "text": content}]
                elif kind == "double_encoded":
                    content = json.dumps(content)
                elif kind == "bom":
                    content = "\ufeff" + content
                elif kind == "malformed":
                    content = '{"geometry_lock":'
                elif kind == "truncated":
                    finish = "length"
            return 200, {
                "id": "wire-plan-" + str(len(self.calls)),
                "choices": [{"finish_reason": finish, "message": {"content": content}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }

    transport = Transport()
    gateway = TengliOpenAICompatibleGateway(
        api_key="offline-test",
        base_url="https://offline.invalid",
        planner_model="configured-planner",
        image_model="gpt-image-2",
        transport=transport,
    )
    harness.gateway.plan = gateway.plan
    result = asyncio.run(provider.execute(request))
    assert result.outcome == ProviderOutcome.SUCCEEDED, result
    assert len(transport.calls) == expected_plans
    assert len(harness.gateway.requests) == 1
    assert result.raw_usage["network_requests"] == expected_plans + 1
    for call in transport.calls:
        assert call["payload"]["response_format"]["type"] == "json_schema"
        assert "response_schema" in call["payload"]["messages"][1]["content"][0]["text"]
    asyncio.run(provider.execute(request))
    assert len(transport.calls) == expected_plans
    assert len(harness.gateway.requests) == 1


@pytest.mark.parametrize(
    "encode",
    [
        lambda v: [v],
        lambda v: "```JSON \r\n" + json.dumps(v) + "\r\n```",
        lambda v: {**v, "geometry_lock": json.dumps(v["geometry_lock"])},
        lambda v: {**v, "reference_facts": json.dumps(v["reference_facts"])},
    ],
)
def test_additional_unambiguous_json_containers(encode):
    assert normalize_brief(encode(brief())) == brief()


@pytest.mark.parametrize("count", [1, 4])
def test_real_provider_reservation_includes_one_bounded_format_repair(
    monkeypatch, settings, count
):
    from types import SimpleNamespace

    from app import routes_v1
    from app.remix_fast_contract import (
        MAX_PLANNER_REQUESTS_PER_IMAGE,
        MAX_REQUESTS_PER_IMAGE,
    )

    settings.task_runner = "tengli"
    settings.reference_remix_provider_enabled = True
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )
    job = SimpleNamespace(
        id="job-format-quota",
        type="reference_remix",
        expected_item_count=count,
        configuration={"settings": {"reference_skill": "aurora-remix-fast"}},
        estimated_cost_max_micros=90_000 * count,
    )
    reservations = []
    monkeypatch.setattr(
        routes_v1,
        "reserve_provider_job_quota",
        lambda *a, **kw: reservations.append(kw),
    )
    routes_v1._reserve_real_provider_job_if_enabled(None, request, job, "user-test")
    assert reservations[0]["provider_request_count"] == MAX_REQUESTS_PER_IMAGE * count
    assert reservations[0]["group_count"] == MAX_PLANNER_REQUESTS_PER_IMAGE * count
    assert (
        reservations[0]["estimated_cost_micros"]
        == 90_000 * count
        + settings.tengli_planner_reserve_micros
        * MAX_PLANNER_REQUESTS_PER_IMAGE
        * count
    )


def test_started_format_repair_cannot_be_dispatched_again(harness, tmp_path):
    from app.models import JobItemRecord
    from app.remix_fast_provider import STATE_KEY

    provider, request = install(harness, tmp_path)
    original = harness.gateway.plan

    async def interrupted(value):
        if harness.gateway.plan_requests:
            raise TimeoutError("repair reply lost")
        return replace(await original(value), payload={})

    harness.gateway.plan = interrupted
    asyncio.run(provider.execute(request))
    with harness.session_factory() as db:
        state = db.get(JobItemRecord, request.job_item_id).configuration[STATE_KEY]
        assert state["preparation_repair"]["state"] == "started"
    result = asyncio.run(provider.execute(request))
    assert result.error_code == "REMIX_FAST_PREPARATION_FAILED"
    assert len(harness.gateway.plan_requests) == 1
    assert harness.gateway.requests == []
