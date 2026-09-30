import asyncio
import base64
import json
import time
from io import BytesIO

import pytest

from app.responses_adapter import (
    ResponsesStreamError,
    read_responses_stream,
    responses_envelope,
    responses_request,
)
from app.xinghe_agent import (
    PlannerRequest,
    SourceImage,
    TengliOpenAICompatibleGateway,
    XingheAgentError,
    _planner_envelope_diagnostics,
    _planner_message_text,
)


def test_native_request_preserves_source_order_bytes_schema_and_limits():
    source = b"exact image bytes"
    uri = "data:image/png;base64," + base64.b64encode(source).decode()
    schema = {"name": "audit", "strict": True, "schema": {"type": "object"}}
    request = responses_request(
        {
            "model": "configured-model",
            "messages": [
                {"role": "system", "content": "identity constraints"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "product then candidate"},
                        {"type": "image_url", "image_url": {"url": uri}},
                    ],
                },
            ],
            "response_format": {"type": "json_schema", "json_schema": schema},
            "max_completion_tokens": 16000,
        }
    )
    assert request["input"][0]["content"] == "identity constraints"
    assert request["input"][1]["content"] == [
        {"type": "input_text", "text": "product then candidate"},
        {"type": "input_image", "image_url": uri, "detail": "high"},
    ]
    assert request["text"]["format"] == {"type": "json_schema", **schema}
    assert request["max_output_tokens"] == 16000
    assert request["store"] is False
    assert request["stream"] is True


@pytest.mark.parametrize(
    "status,reason,refusal",
    [
        ("incomplete", "max_output_tokens", False),
        ("incomplete", "content_filter", False),
        ("failed", None, False),
        ("completed", None, True),
    ],
)
def test_incomplete_or_refused_native_output_cannot_be_accepted(
    status, reason, refusal
):
    envelope = responses_envelope(
        {
            "status": status,
            "incomplete_details": {"reason": reason},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "refusal" if refusal else "output_text",
                            "text": '{"pass":true}',
                        }
                    ],
                }
            ],
        }
    )
    with pytest.raises(XingheAgentError):
        _planner_message_text(envelope)
    if reason == "max_output_tokens":
        assert (
            _planner_envelope_diagnostics(envelope)["provider_envelope"][
                "finish_reason"
            ]
            == "length"
        )


@pytest.mark.parametrize(
    "profile", ["detail_pack", "aurora_style_calibration", "aurora_v20_visual_audit"]
)
def test_gateway_native_planning_reads_images_and_retains_id_usage(profile):
    from app.aurora_main_image_provider import _STYLE_CALIBRATION_SYSTEM_PROMPT

    class Transport:
        calls = []

        async def post_json(self, **kwargs):
            self.calls.append(kwargs)
            return 200, {
                "id": "resp_probe",
                "status": "completed",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "total_tokens": 17,
                },
                "output": [
                    {"type": "reasoning", "summary": [{"text": "not output"}]},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"pixel_reviewed": False}),
                            }
                        ],
                    },
                ],
            }

    transport = Transport()
    gateway = TengliOpenAICompatibleGateway(
        api_key="test",
        base_url="https://example.test",
        planner_model="configured-model",
        image_model="image",
        planner_api_mode="responses",
        transport=transport,
    )
    request = PlannerRequest(
        workspace_id="w",
        job_id="j",
        group_key="g",
        sources=(
            SourceImage(
                asset_id="s",
                group_key="g",
                filename="input.png",
                content_type="image/png",
                sha256="a" * 64,
                payload=b"real source bytes",
                source_role="product_reference",
            ),
        ),
        page_count=1,
        language="zh-CN",
        product_name="Product",
        product_information=(
            json.dumps({"page_contract": {"source_claim": "approved-fact-123"}}),
        ),
        platform_code="tmall",
        size="1024x1024",
        idempotency_key="idem",
        planning_profile=profile,
        system_prompt=_STYLE_CALIBRATION_SYSTEM_PROMPT
        if profile == "aurora_style_calibration"
        else "Detail planning",
    )
    result = asyncio.run(gateway.plan(request))
    assert result.payload == {"pixel_reviewed": False}  # never forge vision evidence
    assert result.provider_request_id == "resp_probe"
    assert result.raw_usage["total_tokens"] == 17
    assert len(transport.calls) == gateway.external_network_request_count == 1
    call = transport.calls[0]
    assert call["url"] == "https://example.test/v1/responses"
    assert call["headers"]["Idempotency-Key"] == "idem"
    if profile.startswith("aurora_"):
        assert "approved-fact-123" in call["payload"]["input"][1]["content"][0]["text"]
    if profile == "aurora_style_calibration":
        assert call["payload"]["max_output_tokens"] == 4096
        wire_prompt = json.dumps(call["payload"]["input"])
        assert "agent_pixel_reviewed=false" in wire_prompt
        assert "decision_summary" not in wire_prompt
        assert "all_material_deficiencies" not in wire_prompt
    assert call["payload"]["input"][1]["content"][-1]["image_url"].endswith(
        base64.b64encode(b"real source bytes").decode()
    )


def _event(event):
    return b"data: " + json.dumps(event).encode() + b"\r\n\r\n"


@pytest.mark.parametrize("status", ["completed", "incomplete", "failed"])
def test_stream_uses_terminal_status_usage_and_output_not_delta(status):
    final = {
        "id": "resp_one",
        "status": status,
        "usage": {"input_tokens": 12},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"valid":true}'}],
            }
        ],
    }
    data = b": heartbeat\r\n\r\n" + _event(
        {"type": "response.output_text.delta", "delta": "WRONG"}
    )
    data += _event({"type": "response." + status, "response": final})
    result = read_responses_stream(BytesIO(data), deadline=time.perf_counter() + 2)
    assert result == final
    envelope = responses_envelope(result)
    if status == "completed":
        assert _planner_message_text(envelope) == '{"valid":true}'
    else:
        with pytest.raises(XingheAgentError):
            _planner_message_text(envelope)


@pytest.mark.parametrize(
    "data",
    [
        b"data: [DONE]\n\n",
        b"data: not JSON\n\n",
        b"data: []\n\n",
        _event({"type": "response.output_text.delta", "delta": '{"valid":true}'}),
        _event({"type": "response.completed", "response": {"status": "incomplete"}}),
        _event({"type": "error", "message": "SECRET"}),
    ],
)
def test_stream_rejects_truncation_invalid_or_inconsistent_terminal(data):
    with pytest.raises(ResponsesStreamError) as error:
        read_responses_stream(BytesIO(data), deadline=time.perf_counter() + 2)
    assert "SECRET" not in str(error.value)


def test_stream_has_total_deadline_and_size_limits():
    with pytest.raises(TimeoutError):
        read_responses_stream(BytesIO(b": heartbeat\n"), deadline=0)
    with pytest.raises(ResponsesStreamError, match="byte limit"):
        read_responses_stream(
            BytesIO(b"data: " + b"x" * (4 * 1024 * 1024)),
            deadline=time.perf_counter() + 2,
        )


def test_transport_decodes_sse_and_keeps_header_request_id(monkeypatch):
    from app.xinghe_agent import UrllibOpenAITransport

    class Response(BytesIO):
        status = 200
        headers = {
            "content-type": "text/event-stream; charset=utf-8",
            "x-request-id": "req_header",
        }

    final = {"status": "completed", "output": [], "usage": {"total_tokens": 12}}
    monkeypatch.setattr(
        "app.xinghe_agent.urlopen",
        lambda *a, **k: Response(
            _event({"type": "response.completed", "response": final})
        ),
    )
    status, result = UrllibOpenAITransport._send("https://example.test", {}, b"{}", 2)
    assert status == 200
    assert result["request_id"] == "req_header"
    assert result["usage"]["total_tokens"] == 12


def test_stream_timeout_keeps_created_response_id_without_content(monkeypatch):
    from app.xinghe_agent import UrllibOpenAITransport

    class Response(BytesIO):
        status = 200
        headers = {"content-type": "text/event-stream"}

        def readline(self, size=-1):
            if self.tell() == len(self.getvalue()):
                raise TimeoutError("SECRET upstream URL")
            return super().readline(size)

    monkeypatch.setattr(
        "app.xinghe_agent.urlopen",
        lambda *a, **k: Response(
            _event({"type": "response.created", "response": {"id": "resp_created"}})
        ),
    )
    with pytest.raises(XingheAgentError) as error:
        UrllibOpenAITransport._send("https://example.test", {}, b"{}", 2)
    assert error.value.provider_request_id == "resp_created"
    assert '"phase": "response_stream"' in str(error.value)
    assert error.value.retryable is False
    assert "SECRET" not in str(error.value)
