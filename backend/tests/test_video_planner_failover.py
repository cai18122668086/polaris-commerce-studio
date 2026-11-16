import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.errors import ApiError
from app.video_assistance_provider import VideoAssistanceProvider


@pytest.fixture
def settings():
    return Settings(_env_file=None).model_copy(
        update={
            "video_script_planning_enabled": True,
            "video_script_base_url": "https://primary.example",
            "video_script_api_key": SecretStr("primary-secret"),
            "video_script_model": "deepseek-v4.1-flash-1017",
            "video_script_fallback_base_url": "https://standby.example",
            "video_script_fallback_api_key": SecretStr("standby-secret"),
            "video_script_fallback_model": "gpt-6.1-sol",
            "video_extract_enabled": True,
            "video_extract_api_key": SecretStr("extract-secret"),
        }
    )


def call(settings, handler, body=None):
    provider = VideoAssistanceProvider(settings, httpx.MockTransport(handler))
    return provider.request(
        "planner",
        "POST",
        "/v1/chat/completions",
        json=body or {"model": settings.video_script_model, "messages": []},
    )


def test_primary_success_never_calls_standby(settings):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        assert request.headers["Authorization"] == "Bearer primary-secret"
        return httpx.Response(200, json={"id": "primary-response"})

    assert call(settings, handler)["id"] == "primary-response"
    assert seen == ["primary.example"]


def test_standby_does_not_receive_deepseek_only_thinking_option(settings):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "primary.example":
            return httpx.Response(429)
        assert json.loads(request.content) == {"model": "gpt-6.1-sol"}
        return httpx.Response(200, json={"id": "standby"})

    call(
        settings,
        handler,
        {"model": settings.video_script_model, "thinking": {"type": "disabled"}},
    )
    assert seen == ["primary.example", "standby.example"]


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429])
def test_pre_execution_rejection_uses_standby_once(settings, status):
    seen = []
    body = {
        "model": settings.video_script_model,
        "messages": [{"role": "user", "content": "hello"}],
    }

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "primary.example":
            return httpx.Response(status)
        assert request.headers["Authorization"] == "Bearer standby-secret"
        sent = json.loads(request.content)
        assert sent == {**body, "model": "gpt-6.1-sol"}
        return httpx.Response(
            200, json={"id": "standby-response", "model": "gpt-6.1-sol"}
        )

    result = call(settings, handler, body)
    assert seen == ["primary.example", "standby.example"]
    assert body["model"] == "deepseek-v4.1-flash-1017"
    assert result["_polaris_planner_route"] == {
        "channel": "fallback",
        "host": "standby.example",
        "model": "gpt-6.1-sol",
        "reason": f"http_{status}",
    }
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
def test_uncertain_http_outcome_never_calls_standby(settings, status):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(status)

    with pytest.raises(ApiError) as error:
        call(settings, handler)
    assert error.value.code == "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN"
    assert seen == ["primary.example"]


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError]
)
def test_uncertain_transport_outcome_never_calls_standby(settings, failure):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        raise failure("ambiguous outcome", request=request)

    with pytest.raises(ApiError) as error:
        call(settings, handler)
    assert error.value.code == "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN"
    assert seen == ["primary.example"]


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
def test_connection_not_established_can_use_standby(settings, failure):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "primary.example":
            raise failure("connection failed", request=request)
        return httpx.Response(200, json={"id": "standby-response"})

    result = call(settings, handler)
    assert result["_polaris_planner_route"]["reason"] == "connection_not_established"
    assert seen == ["primary.example", "standby.example"]


def test_malformed_response_does_not_repeat_generation(settings):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(ApiError) as error:
        call(settings, handler)
    assert error.value.code == "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN"
    assert seen == ["primary.example"]


def test_standby_timeout_does_not_loop_back_to_primary(settings):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "primary.example":
            return httpx.Response(429)
        raise httpx.ReadTimeout("standby outcome unknown", request=request)

    with pytest.raises(ApiError) as error:
        call(settings, handler)
    assert error.value.code == "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN"
    assert seen == ["primary.example", "standby.example"]


def test_transcript_extraction_does_not_use_planner_standby(settings):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(429)

    provider = VideoAssistanceProvider(settings, httpx.MockTransport(handler))
    with pytest.raises(ApiError):
        provider.request("extract", "POST", "/api/v1/jobs", json={})
    assert seen == ["api.everyinfra.com"]


@pytest.mark.parametrize(
    "url",
    [
        "http://standby.example",
        "https://user:pass@standby.example",
        "https://standby.example?key=secret",
        "https://primary.example",
    ],
)
def test_invalid_or_identical_standby_is_not_used(settings, url):
    settings = settings.model_copy(update={"video_script_fallback_base_url": url})
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(429)

    with pytest.raises(ApiError) as error:
        call(settings, handler)
    assert error.value.code == "VIDEO_ASSISTANCE_REJECTED"
    assert seen == ["primary.example"]
