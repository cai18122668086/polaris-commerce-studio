"""Production model and provider-route policy (non-secret values only).

This file is the versioned record of how production picks its planning and
image accounts. It carries endpoints, model names and route order. Provider
keys never live here: they are injected on the server from the existing
private env/override files, and this module only ever reports how many keys a
service has, never their values.

Planning, vision and review requests (``_ordered_routes``):
    ooapi accounts (POLARIS_PROVIDER_FAILOVER_*), top to bottom,
    then api.jgshai.cn (POLARIS_ANALYSIS_*) as the last fallback.
Image requests (``_image_routes``):
    api.artflow.vip (POLARIS_IMAGE_*) first,
    then api.jgshai.cn (POLARIS_TENGLI_*) as the image fallback.

Run ``python3 deploy/provider_routes.py`` on the production host (as a user
that may run ``docker inspect``) to compare the running services with this
policy. It is read-only: it never starts, restarts or changes a container.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence

MAIN_IMAGE_MODEL = "gpt-6.1-sol"

# Values written into deploy/compose.production.yml defaults and
# deploy/.env.production.example. Keys are injected separately (SECRET_KEYS).
PRODUCTION_PROVIDER_ROUTES: dict[str, str] = {
    "POLARIS_ANALYSIS_BASE_URL": "https://api.jgshai.cn",
    "POLARIS_ANALYSIS_MODEL": "gpt-6.1-sol",
    "POLARIS_TENGLI_VISION_MODEL": "gpt-6.1-sol",
    "POLARIS_MAIN_IMAGE_PLANNER_MODEL": MAIN_IMAGE_MODEL,
    "POLARIS_MAIN_IMAGE_FAILOVER_PLANNER_MODEL": "",
    "POLARIS_PROVIDER_FAILOVER_ENABLED": "true",
    "POLARIS_PROVIDER_FAILOVER_BASE_URL": "https://api.ooapi.cc",
    "POLARIS_PROVIDER_FAILOVER_MODEL": "gpt-6.1-sol",
    # "failover" is the route name when exactly one ooapi key is configured;
    # with several keys they are failover-1, failover-2, ... Listing both keeps
    # ooapi ahead of api.jgshai.cn whatever the key count.
    "POLARIS_PROVIDER_ROTATION_ORDER": (
        "failover,failover-1,failover-2,failover-3,failover-4,primary"
    ),
    "POLARIS_IMAGE_BASE_URL": "https://api.artflow.vip",
    "POLARIS_IMAGE_MODEL": "gpt-image-2.5-flare",
    "POLARIS_TENGLI_BASE_URL": "https://api.jgshai.cn",
    "POLARIS_TENGLI_IMAGE_MODEL": "gpt-image-2",
    "POLARIS_REPLICA_IMAGE_FAILOVER_ENABLED": "true",
}

SECRET_KEYS = (
    "POLARIS_ANALYSIS_API_KEY",
    "POLARIS_PROVIDER_FAILOVER_API_KEY",
    "POLARIS_IMAGE_API_KEY",
    "POLARIS_TENGLI_API_KEY",
)

# Production backend services that plan, review or generate images. The
# dispatcher only routes Celery work and is not checked.
CHECKED_SERVICES = (
    "api",
    "worker",
    "detail-api",
    "detail-worker",
    "replica-api",
    "replica-worker",
)
CONTAINER_NAME = "polaris-production-{service}-1"
EXPECTED_FAILOVER_KEY_COUNT = 4


def _host(url: str) -> str:
    return re.sub(r"^https?://", "", (url or "").strip()).rstrip("/")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() == "true"


def split_keys(value: str | None) -> list[str]:
    return [part for part in re.split(r"[\s,]+", value or "") if part]


def planner_route_names(rotation_order: str, failover_key_count: int) -> list[str]:
    """Mirror TengliOpenAICompatibleGateway._ordered_routes route naming."""

    routes = ["primary"]
    if failover_key_count == 1:
        routes.append("failover")
    elif failover_key_count > 1:
        routes.extend(f"failover-{i}" for i in range(1, failover_key_count + 1))
    ordered: list[str] = []
    for name in (part.strip().lower() for part in rotation_order.split(",")):
        if name in routes and name not in ordered:
            ordered.append(name)
    if not ordered:
        ordered = ["primary"]
    ordered.extend(name for name in routes if name not in ordered)
    return ordered


def effective_routes(env: Mapping[str, str]) -> dict[str, object]:
    """Summarise what a service will actually call, without any key value."""

    failover_keys = (
        split_keys(env.get("POLARIS_PROVIDER_FAILOVER_API_KEY"))
        if _truthy(env.get("POLARIS_PROVIDER_FAILOVER_ENABLED"))
        else []
    )
    names = planner_route_names(
        env.get("POLARIS_PROVIDER_ROTATION_ORDER", "primary,failover"),
        len(failover_keys),
    )
    analysis_model = env.get("POLARIS_ANALYSIS_MODEL", "")
    failover_model = env.get("POLARIS_PROVIDER_FAILOVER_MODEL", "") or analysis_model
    main_model = env.get("POLARIS_MAIN_IMAGE_PLANNER_MODEL", "").strip()
    main_failover = env.get("POLARIS_MAIN_IMAGE_FAILOVER_PLANNER_MODEL", "").strip()
    planner = []
    main_image = []
    for name in names:
        if name == "primary":
            host = _host(env.get("POLARIS_ANALYSIS_BASE_URL", ""))
            model = analysis_model
            main = main_model or model
        else:
            host = _host(env.get("POLARIS_PROVIDER_FAILOVER_BASE_URL", ""))
            model = failover_model
            main = main_failover or main_model or model
        planner.append(f"{name}@{host}:{model}")
        main_image.append(main)
    image_host = _host(env.get("POLARIS_IMAGE_BASE_URL", ""))
    images = [f"primary@{image_host}:{env.get('POLARIS_IMAGE_MODEL', '')}"]
    if _truthy(env.get("POLARIS_REPLICA_IMAGE_FAILOVER_ENABLED")) and env.get(
        "POLARIS_TENGLI_API_KEY"
    ):
        fallback_host = _host(env.get("POLARIS_TENGLI_BASE_URL", ""))
        fallback_model = env.get("POLARIS_TENGLI_IMAGE_MODEL", "")
        images.append(f"image-failover@{fallback_host}:{fallback_model}")
    return {
        "planner_routes": planner,
        "main_image_models": sorted(set(main_image)),
        "vision_model": env.get("POLARIS_TENGLI_VISION_MODEL", ""),
        "image_routes": images,
        "failover_key_count": len(failover_keys),
        "failover_keys_unique": len(set(failover_keys)) == len(failover_keys),
        "secret_keys_present": sorted(k for k in SECRET_KEYS if env.get(k)),
    }


def expected_routes(
    failover_key_count: int = EXPECTED_FAILOVER_KEY_COUNT,
) -> dict[str, object]:
    env = dict(PRODUCTION_PROVIDER_ROUTES)
    env["POLARIS_PROVIDER_FAILOVER_API_KEY"] = ",".join(
        f"placeholder-{i}" for i in range(failover_key_count)
    )
    for key in SECRET_KEYS:
        env.setdefault(key, "placeholder")
        if not env[key]:
            env[key] = "placeholder"
    return effective_routes(env)


def compare(env: Mapping[str, str]) -> list[str]:
    """Return human-readable differences; never includes a key value."""

    actual = effective_routes(env)
    want = expected_routes()
    problems = [
        f"{field}: running={actual[field]!r} policy={want[field]!r}"
        for field in (
            "planner_routes",
            "main_image_models",
            "vision_model",
            "image_routes",
            "failover_key_count",
            "secret_keys_present",
        )
        if actual[field] != want[field]
    ]
    if not actual["failover_keys_unique"]:
        problems.append("failover keys: duplicates configured")
    return problems


def docker_env(
    container: str, runner: Callable[..., object] = subprocess.run
) -> dict[str, str]:
    completed = runner(
        ["docker", "inspect", "--format", "{{json .Config.Env}}", container],
        capture_output=True,
        text=True,
        check=True,
    )
    pairs = json.loads(completed.stdout)
    return dict(item.split("=", 1) for item in pairs if "=" in item)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("services", nargs="*", default=list(CHECKED_SERVICES))
    args = parser.parse_args(argv)
    failed = False
    for service in args.services:
        try:
            env = docker_env(CONTAINER_NAME.format(service=service))
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            print(f"{service}: cannot inspect ({type(exc).__name__})")
            failed = True
            continue
        problems = compare(env)
        if problems:
            failed = True
            print(f"{service}: DIFFERS")
            for line in problems:
                print(f"  - {line}")
        else:
            routes = effective_routes(env)
            print(
                f"{service}: OK planner={' > '.join(routes['planner_routes'])} "
                f"images={' > '.join(routes['image_routes'])}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
