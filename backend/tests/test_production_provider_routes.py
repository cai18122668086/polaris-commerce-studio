"""The versioned production route policy must match what the gateway builds."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.config import Settings
from app.xinghe_agent import build_tengli_gateway

_POLICY_PATH = Path(__file__).resolve().parents[2] / "deploy" / "provider_routes.py"
_spec = importlib.util.spec_from_file_location("provider_routes", _POLICY_PATH)
assert _spec and _spec.loader
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)


def _policy_env(monkeypatch, failover_key_count: int) -> dict[str, str]:
    env = dict(policy.PRODUCTION_PROVIDER_ROUTES)
    env.update(
        {
            "POLARIS_ANALYSIS_API_KEY": "offline-primary",
            "POLARIS_IMAGE_API_KEY": "offline-image",
            "POLARIS_TENGLI_API_KEY": "offline-tengli",
            "POLARIS_PROVIDER_FAILOVER_API_KEY": ",".join(
                f"offline-failover-{i}" for i in range(failover_key_count)
            ),
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def _host(url: str) -> str:
    return urlparse(url).netloc


@pytest.mark.parametrize("failover_key_count", [0, 1, 2, 4, 5])
def test_policy_mirror_matches_gateway(monkeypatch, failover_key_count):
    env = _policy_env(monkeypatch, failover_key_count)
    gateway = build_tengli_gateway(Settings())
    built = [
        f"{route.name}@{_host(route.planner_base_url)}:{route.planner_model}"
        for route in gateway._ordered_routes()
    ]
    images = [
        f"{route.name}@{_host(route.image_base_url)}:{route.image_model}"
        for route in gateway._image_routes()
    ]
    mirrored = policy.effective_routes(env)
    assert built == mirrored["planner_routes"]
    assert images == mirrored["image_routes"]


@pytest.mark.parametrize("failover_key_count", [1, 2, 4])
def test_ooapi_first_and_jgshai_last(monkeypatch, failover_key_count):
    _policy_env(monkeypatch, failover_key_count)
    gateway = build_tengli_gateway(Settings())
    hosts = [_host(route.planner_base_url) for route in gateway._ordered_routes()]
    assert hosts[:-1] == ["api.ooapi.cc"] * failover_key_count
    assert hosts[-1] == "api.jgshai.cn"
    assert {route.planner_model for route in gateway._ordered_routes()} == {
        "gpt-6.1-sol"
    }
    assert gateway._main_image_planner_model == "gpt-6.1-sol"
    assert gateway.vision_model == "gpt-6.1-sol"
    images = [_host(route.image_base_url) for route in gateway._image_routes()]
    assert images == ["api.artflow.vip", "api.jgshai.cn"]


def test_policy_holds_no_secret():
    for key in policy.SECRET_KEYS:
        assert key not in policy.PRODUCTION_PROVIDER_ROUTES
    for value in policy.PRODUCTION_PROVIDER_ROUTES.values():
        assert not value.startswith("sk-")
