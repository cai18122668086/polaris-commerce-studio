import asyncio
import base64
import json

import pytest

from app.responses_adapter import responses_envelope, responses_request
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


def test_gateway_native_planning_reads_images_and_retains_id_usage():
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
        product_information=(),
        platform_code="tmall",
        size="1024x1024",
        idempotency_key="idem",
    )
    result = asyncio.run(gateway.plan(request))
    assert result.payload == {"pixel_reviewed": False}  # never forge vision evidence
    assert result.provider_request_id == "resp_probe"
    assert result.raw_usage["total_tokens"] == 17
    assert len(transport.calls) == gateway.external_network_request_count == 1
    call = transport.calls[0]
    assert call["url"] == "https://example.test/v1/responses"
    assert call["headers"]["Idempotency-Key"] == "idem"
    assert call["payload"]["input"][1]["content"][-1]["image_url"].endswith(
        base64.b64encode(b"real source bytes").decode()
    )
