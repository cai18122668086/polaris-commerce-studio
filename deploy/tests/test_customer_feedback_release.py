"""Release configuration preserves role isolation and literal runtime secrets."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_customer_feedback import ROLES, runtime_config


class FeedbackReleaseTests(unittest.TestCase):
    def fixture(self):
        canonical = {
            "name": "polaris-production",
            "services": {},
            "networks": {"private": {"name": "existing-private", "driver": "bridge"}},
            "volumes": {"harness": {"name": "existing-harness", "driver": "local"}},
        }
        live, images = {}, {}
        for index, role in enumerate(ROLES):
            canonical["services"][role] = {
                "image": "prior:tag", "read_only": True, "cap_drop": ["ALL"],
                "depends_on": {"redis": {"condition": "service_healthy"}},
                "networks": {"private": None}, "mem_limit": 384 * 1024 * 1024,
                "command": ["old", "canonical"],
                "environment": {"SYNTHETIC_SECRET": "incorrect-canonical-copy"},
                "volumes": [{"type": "volume", "source": "harness", "target": "/app/.data"}],
            }
            live[role] = {
                "Image": "sha256:" + str(index) * 64,
                "Config": {"Env": ["SYNTHETIC_SECRET=literal$secret", "ROLE=" + role],
                           "Cmd": ["worker", "--queues=" + role], "Entrypoint": None,
                           "Healthcheck": {"Test": ["CMD-SHELL", "test $ROLE"],
                                           "Interval": 1000000000, "Retries": 3}},
            }
            images[role] = "sha256:" + "f" * 64
        canonical["services"]["caddy"] = {"image": "untouched:proxy"}
        return canonical, live, images

    def test_preserves_roles_secrets_limits_and_exact_rollback(self):
        source, live, images = self.fixture()
        before = deepcopy(source)
        active, rollback = runtime_config(source, live, images, "a" * 40)
        self.assertEqual(source, before)
        self.assertEqual(set(active["services"]), set(ROLES))
        self.assertEqual(active["networks"]["private"], {"name": "existing-private", "external": True})
        self.assertEqual(active["volumes"]["harness"], {"name": "existing-harness", "external": True})
        for role in ROLES:
            new, old = active["services"][role], rollback["services"][role]
            self.assertEqual(new["environment"]["SYNTHETIC_SECRET"], "literal$$secret")
            self.assertEqual(new["command"], live[role]["Config"]["Cmd"])
            self.assertEqual(new["healthcheck"]["test"], ["CMD-SHELL", "test $$ROLE"])
            self.assertEqual(new["mem_limit"], source["services"][role]["mem_limit"])
            self.assertEqual(old["image"], live[role]["Image"])
            self.assertNotIn("depends_on", new)
            self.assertNotIn("POLARIS_IMAGE_GLOBAL_CONCURRENCY", old["environment"])
            if role != "frontend":
                self.assertEqual(new["environment"]["POLARIS_IMAGE_GLOBAL_CONCURRENCY"], "3000")

    def test_rejects_public_or_writable_role(self):
        for change in ({"ports": ["8000:8000"]}, {"read_only": False}, {"cap_drop": []}):
            with self.subTest(change=change):
                source, live, images = self.fixture()
                source["services"]["api"].update(change)
                with self.assertRaises(ValueError):
                    runtime_config(source, live, images, "a" * 40)


if __name__ == "__main__":
    unittest.main()
