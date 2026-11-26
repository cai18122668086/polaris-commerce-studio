from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

import provider_routes as policy
from generate_production_env import DEFAULT_PROVIDER_VALUES, load_env

SECRET_VALUE = "sk-must-never-be-printed"


def production_env(**overrides: str) -> dict[str, str]:
    env = dict(policy.PRODUCTION_PROVIDER_ROUTES)
    env.update(
        {
            "POLARIS_ANALYSIS_API_KEY": SECRET_VALUE,
            "POLARIS_IMAGE_API_KEY": SECRET_VALUE,
            "POLARIS_TENGLI_API_KEY": SECRET_VALUE,
            "POLARIS_PROVIDER_FAILOVER_API_KEY": ",".join(
                f"{SECRET_VALUE}-{i}" for i in range(4)
            ),
            # Production's literal order before this policy was versioned.
            "POLARIS_PROVIDER_ROTATION_ORDER": (
                "failover-1,failover-2,failover-3,failover-4,primary"
            ),
        }
    )
    env.update(overrides)
    return env


class RouteOrderTest(unittest.TestCase):
    def test_ooapi_first_for_any_key_count(self) -> None:
        order = policy.PRODUCTION_PROVIDER_ROUTES["POLARIS_PROVIDER_ROTATION_ORDER"]
        self.assertEqual(policy.planner_route_names(order, 0), ["primary"])
        self.assertEqual(policy.planner_route_names(order, 1), ["failover", "primary"])
        self.assertEqual(
            policy.planner_route_names(order, 4),
            ["failover-1", "failover-2", "failover-3", "failover-4", "primary"],
        )
        for count in (2, 4, 5, 9, 16):
            with self.subTest(count=count):
                self.assertEqual(
                    policy.planner_route_names(order, count),
                    [f"failover-{i}" for i in range(1, count + 1)] + ["primary"],
                )

    def test_old_literal_order_would_put_jgshai_first(self) -> None:
        old = "failover-1,failover-2,failover-3,failover-4,primary"
        self.assertEqual(policy.planner_route_names(old, 1), ["primary", "failover"])
        self.assertEqual(
            policy.planner_route_names(old, 5)[-2:], ["primary", "failover-5"]
        )

    def test_policy_order_on_an_image_without_the_wildcard(self) -> None:
        # Images built before "failover-*" ignore it; today's four keys stay first.
        order = policy.PRODUCTION_PROVIDER_ROUTES["POLARIS_PROVIDER_ROTATION_ORDER"]
        legacy = ",".join(p for p in order.split(",") if p != "failover-*")
        self.assertEqual(
            policy.planner_route_names(legacy, 4),
            ["failover-1", "failover-2", "failover-3", "failover-4", "primary"],
        )

    def test_effective_routes(self) -> None:
        routes = policy.effective_routes(production_env())
        self.assertEqual(
            routes["planner_routes"],
            [f"failover-{i}@api.ooapi.cc:gpt-6.1-sol" for i in range(1, 5)]
            + ["primary@api.jgshai.cn:gpt-6.1-sol"],
        )
        self.assertEqual(
            routes["image_routes"],
            [
                "primary@api.artflow.vip:gpt-image-2.5-flare",
                "image-failover@api.jgshai.cn:gpt-image-2",
            ],
        )
        self.assertEqual(routes["main_image_models"], ["gpt-6.1-sol"])

    def test_running_production_shape_matches_policy(self) -> None:
        self.assertEqual(policy.compare(production_env()), [])
        # Services other than the worker leave the main-image model empty;
        # their effective model is still the shared gpt-6.1-sol.
        self.assertEqual(
            policy.compare(production_env(POLARIS_MAIN_IMAGE_PLANNER_MODEL="")), []
        )

    def test_differences_are_reported_without_key_values(self) -> None:
        cases = {
            "primary first": {"POLARIS_PROVIDER_ROTATION_ORDER": "primary,failover"},
            "old model": {"POLARIS_PROVIDER_FAILOVER_MODEL": "gpt-5.6-sol"},
            "no image fallback": {"POLARIS_REPLICA_IMAGE_FAILOVER_ENABLED": "false"},
            "three keys": {
                "POLARIS_PROVIDER_FAILOVER_API_KEY": ",".join([SECRET_VALUE] * 3)
            },
            "failover off": {"POLARIS_PROVIDER_FAILOVER_ENABLED": "false"},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                problems = policy.compare(production_env(**overrides))
                self.assertTrue(problems)
                self.assertNotIn(SECRET_VALUE, "\n".join(problems))
        duplicated = policy.compare(
            production_env(
                POLARIS_PROVIDER_FAILOVER_API_KEY=",".join([SECRET_VALUE] * 4)
            )
        )
        self.assertIn("failover keys: duplicates configured", duplicated)

    def test_cli_never_prints_key_values(self) -> None:
        env = production_env()

        def runner(cmd, **_kwargs):
            self.assertEqual(cmd[:2], ["docker", "inspect"])
            pairs = [f"{k}={v}" for k, v in env.items()]
            return SimpleNamespace(stdout=json.dumps(pairs))

        original = policy.docker_env
        policy.docker_env = lambda container: original(container, runner=runner)
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                code = policy.main(["worker", "replica-api"])
        finally:
            policy.docker_env = original
        self.assertEqual(code, 0)
        self.assertIn("worker: OK", out.getvalue())
        self.assertNotIn(SECRET_VALUE, out.getvalue())

    def test_cli_reports_uninspectable_service(self) -> None:
        original = policy.docker_env

        def broken(container):
            raise subprocess.CalledProcessError(1, ["docker"])

        policy.docker_env = broken
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(policy.main(["worker"]), 1)
        finally:
            policy.docker_env = original


class VersionedFilesTest(unittest.TestCase):
    def test_compose_defaults_follow_policy(self) -> None:
        compose = (DEPLOY / "compose.production.yml").read_text(encoding="utf-8")
        for key, value in policy.PRODUCTION_PROVIDER_ROUTES.items():
            with self.subTest(key):
                match = re.search(
                    rf"^  {key}: \"?\$\{{{key}:-([^}}]*)\}}\"?$", compose, re.MULTILINE
                )
                self.assertIsNotNone(match, f"{key} missing from provider environment")
                self.assertEqual(match.group(1), value)
        for key in policy.SECRET_KEYS:
            with self.subTest(key):
                self.assertRegex(compose, rf"(?m)^  {key}: \$\{{{key}:-\}}$")

    def test_env_example_follows_policy_without_secrets(self) -> None:
        example = load_env(DEPLOY / ".env.production.example")
        for key, value in policy.PRODUCTION_PROVIDER_ROUTES.items():
            with self.subTest(key):
                self.assertEqual(example.get(key), value)
        for key in policy.SECRET_KEYS:
            if key in example:
                self.assertTrue(example[key].startswith("<"), key)

    def test_generator_defaults_follow_policy(self) -> None:
        for key, value in DEFAULT_PROVIDER_VALUES.items():
            if key in policy.PRODUCTION_PROVIDER_ROUTES:
                with self.subTest(key):
                    self.assertEqual(value, policy.PRODUCTION_PROVIDER_ROUTES[key])


if __name__ == "__main__":
    unittest.main()
