import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from app.masked_repair import (
    MaskedEditGatewayRequest,
    MaskedVisualReviewRequest,
)
from app.xinghe_agent import TengliOpenAICompatibleGateway


class CapturingTransport:
    def __init__(self) -> None:
        self.headers: Mapping[str, str] = {}
        self.fields: Sequence[tuple[str, str]] = ()
        self.files: Sequence[tuple[str, str, str, bytes]] = ()

    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]:
        raise AssertionError("Masked edit must not use the JSON endpoint.")

    async def post_multipart(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        fields: Sequence[tuple[str, str]],
        files: Sequence[tuple[str, str, str, bytes]],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]:
        assert url.endswith("/v1/images/edits")
        assert timeout_seconds > 0
        self.headers = headers
        self.fields = fields
        self.files = files
        return 400, {"id": "request_bad_mask", "error": {"code": "invalid_mask"}}


def test_tengli_masked_edit_uses_dedicated_source_mask_contract() -> None:
    transport = CapturingTransport()
    gateway = TengliOpenAICompatibleGateway(
        api_key="test-placeholder-key",
        base_url="https://provider.invalid",
        planner_model="planner-test",
        image_model="configured-but-not-used-for-local-edit",
        transport=transport,
    )
    request = MaskedEditGatewayRequest(
        source_png=b"normalized-source",
        api_mask_png=b"api-mask",
        prompt="master prompt with user instruction",
        quality="medium",
        width=640,
        height=640,
        idempotency_key="durable-attempt-key",
    )

    result = asyncio.run(gateway.edit_masked(request))

    fields = dict(transport.fields)
    assert fields["model"] == "gpt-image-2"
    assert fields["size"] == "640x640"
    assert fields["output_format"] == "png"
    assert fields["response_format"] == "b64_json"
    assert "input_fidelity" not in fields
    assert [file[0] for file in transport.files] == ["image", "mask"]
    assert transport.files[0][1:] == (
        "source.png",
        "image/png",
        b"normalized-source",
    )
    assert transport.files[1][1:] == (
        "mask_api.png",
        "image/png",
        b"api-mask",
    )
    assert transport.headers["Idempotency-Key"] == "durable-attempt-key"
    assert result.http_status == 400
    assert result.retryable is False
    assert result.error_code == "LOCAL_EDIT_REQUEST_FAILED"


class VisualReviewTransport:
    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def post_json(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.call = kwargs
        return (
            200,
            {
                "id": "review_request",
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"visual_success":true,'
                                '"instruction_satisfied":true,'
                                '"identity_inside_selection_preserved":true,'
                                '"boundary_continuity":true,'
                                '"artifacts_absent":true,'
                                '"reason_codes":["passed"],'
                                '"summary":"The candidate passes review."}'
                            )
                        }
                    }
                ],
            },
        )

    async def post_multipart(self, **_: Any) -> tuple[int, dict[str, Any]]:
        raise AssertionError("Visual review must use the JSON endpoint.")


def test_tengli_visual_review_sends_three_ordered_images_once() -> None:
    transport = VisualReviewTransport()
    gateway = TengliOpenAICompatibleGateway(
        api_key="test-placeholder-key",
        base_url="https://provider.invalid",
        planner_model="planner-test",
        image_model="gpt-image-2",
        transport=transport,
    )
    result = asyncio.run(
        gateway.review_masked(
            MaskedVisualReviewRequest(
                source_png=b"source",
                authority_png=b"authority",
                candidate_png=b"candidate",
                instruction="replace the selected label",
                idempotency_key="visual-review-idem",
            )
        )
    )

    assert result.visual_success is True
    assert result.reason_codes == ("passed",)
    assert transport.call is not None
    payload = transport.call["payload"]
    assert payload["model"] == "planner-test"
    assert payload["response_format"] == {"type": "json_object"}
    assert transport.call["headers"]["Idempotency-Key"] == "visual-review-idem"
    content = payload["messages"][1]["content"]
    images = [item for item in content if item["type"] == "image_url"]
    assert len(images) == 3
    assert images[0]["image_url"]["url"].endswith("c291cmNl")
    assert images[1]["image_url"]["url"].endswith("YXV0aG9yaXR5")
    assert images[2]["image_url"]["url"].endswith("Y2FuZGlkYXRl")
