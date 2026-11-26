"""Main-image planning can use its own model; every other caller is unchanged.

No network: a fake transport records the model sent on each route.
"""

import asyncio
import json

import pytest
from pydantic import SecretStr

from app import aurora_main_image_authored as authored
from app import aurora_main_image_native_fast as native_fast
from app.config import Settings
from app.xinghe_agent import (
    MAIN_IMAGE_PLANNER_PROFILES,
    PlannerRequest,
    TengliOpenAICompatibleGateway,
    build_tengli_gateway,
)

PRIMARY = "https://primary.invalid"
FAILOVER = "https://fallback.invalid"


class Transport:
    """Primary answers with ``primary_status``; the failover route answers 200."""

    def __init__(self, primary_status=200, content=None):
        self.primary_status = primary_status
        self.content = content if content is not None else {}
        self.calls = []

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        primary = kwargs["url"].startswith(PRIMARY + "/")
        status = self.primary_status if primary else 200
        if status >= 400:
            return status, {"error": {"message": "upstream unavailable"}}
        return status, {
            "id": "offline-receipt",
            "model": kwargs["payload"]["model"],
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(self.content)},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }

    def models(self):
        return [
            (
                "primary" if c["url"].startswith(PRIMARY + "/") else "failover",
                c["payload"]["model"],
            )
            for c in self.calls
        ]


def gateway(transport, **overrides):
    return TengliOpenAICompatibleGateway(
        api_key="offline-placeholder",
        base_url=PRIMARY,
        planner_model="shared-primary-model",
        image_model="image-model",
        transport=transport,
        failover_enabled=True,
        failover_api_key="offline-fallback-placeholder",
        failover_base_url=FAILOVER,
        failover_model="shared-failover-model",
        **overrides,
    )


def request(profile, system_prompt="system"):
    return PlannerRequest(
        workspace_id="workspace",
        job_id="job-offline",
        group_key="job-offline",
        sources=(),
        page_count=6,
        language="zh-CN",
        product_name="湿巾",
        product_information=("80抽/包",),
        platform_code="TAOBAO_DOMESTIC_MAIN_IMAGE",
        size="1024x1024",
        idempotency_key=f"offline-{profile}",
        planning_profile=profile,
        system_prompt=system_prompt,
    )


def authored_request():
    return request(authored.PROFILE, authored.system_prompt())


def test_profiles_are_exactly_the_main_image_planners():
    assert {authored.PROFILE, native_fast.PROFILE} == MAIN_IMAGE_PLANNER_PROFILES


def test_main_image_uses_its_model_on_the_primary_route():
    transport = Transport(content=authored.fake_strategy("湿巾", 1))
    provider = gateway(transport, main_image_planner_model="gpt-6.1-sol")
    asyncio.run(provider.plan(authored_request()))
    assert transport.models()[0] == ("primary", "gpt-6.1-sol")


def test_main_image_keeps_its_model_after_failover():
    transport = Transport(primary_status=503, content=authored.fake_strategy("湿巾", 1))
    provider = gateway(transport, main_image_planner_model="gpt-6.1-sol")
    result = asyncio.run(provider.plan(authored_request()))
    assert transport.models() == [
        ("primary", "gpt-6.1-sol"),
        ("failover", "gpt-6.1-sol"),
    ]
    assert result.error_code is None


def test_failover_specific_model_applies_to_failover_routes_only():
    transport = Transport(primary_status=503, content=authored.fake_strategy("湿巾", 1))
    provider = gateway(
        transport,
        main_image_planner_model="primary-main-model",
        main_image_failover_planner_model="failover-main-model",
    )
    asyncio.run(provider.plan(authored_request()))
    assert transport.models() == [
        ("primary", "primary-main-model"),
        ("failover", "failover-main-model"),
    ]


def test_failover_specific_model_alone_leaves_primary_on_shared_model():
    transport = Transport(primary_status=503, content=authored.fake_strategy("湿巾", 1))
    provider = gateway(transport, main_image_failover_planner_model="gpt-6.1-sol")
    asyncio.run(provider.plan(authored_request()))
    assert transport.models() == [
        ("primary", "shared-primary-model"),
        ("failover", "gpt-6.1-sol"),
    ]


def test_native_fast_identity_also_uses_the_main_image_model():
    transport = Transport()
    provider = gateway(transport, main_image_planner_model="gpt-6.1-sol")
    asyncio.run(provider.plan(request(native_fast.PROFILE)))
    # Native identity keeps its single-route policy; only the model changes.
    assert transport.models() == [("primary", "gpt-6.1-sol")]


@pytest.mark.parametrize("profile", ["creative_image", "detail_pack"])
def test_other_features_keep_the_shared_models(profile):
    transport = Transport(primary_status=503)
    provider = gateway(
        transport,
        main_image_planner_model="gpt-6.1-sol",
        main_image_failover_planner_model="gpt-6.1-sol",
    )
    asyncio.run(provider.plan(request(profile)))
    assert transport.models()[0] == ("primary", "shared-primary-model")
    assert all(model != "gpt-6.1-sol" for _, model in transport.models())
    if len(transport.calls) > 1:
        assert transport.models()[1] == ("failover", "shared-failover-model")


def test_unset_keeps_the_previous_behaviour_for_main_image():
    transport = Transport(primary_status=503, content=authored.fake_strategy("湿巾", 1))
    provider = gateway(transport)
    asyncio.run(provider.plan(authored_request()))
    assert transport.models() == [
        ("primary", "shared-primary-model"),
        ("failover", "shared-failover-model"),
    ]


def test_settings_reach_the_gateway(settings, monkeypatch):
    settings = settings.model_copy(
        update={"tengli_api_key": SecretStr("offline-placeholder")}
    )
    assert Settings.model_fields["main_image_planner_model"].default == ""
    assert Settings.model_fields["main_image_failover_planner_model"].default == ""
    unset = build_tengli_gateway(settings)
    assert unset._main_image_planner_model == ""
    assert unset._main_image_failover_planner_model == ""
    configured = build_tengli_gateway(
        settings.model_copy(
            update={
                "main_image_planner_model": " gpt-6.1-sol ",
                "main_image_failover_planner_model": "",
            }
        )
    )
    assert configured._main_image_planner_model == "gpt-6.1-sol"
    assert configured._main_image_failover_planner_model == ""
    # The shared models are untouched by the main-image setting.
    assert configured.planner_model == settings.analysis_model


def test_environment_variable_names(monkeypatch):
    monkeypatch.setenv("POLARIS_MAIN_IMAGE_PLANNER_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("POLARIS_MAIN_IMAGE_FAILOVER_PLANNER_MODEL", "fo-model")
    loaded = Settings()
    assert loaded.main_image_planner_model == "gpt-6.1-sol"
    assert loaded.main_image_failover_planner_model == "fo-model"
