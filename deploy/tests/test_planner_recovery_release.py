"""Planner configuration must use one primary key and keep image settings out."""

import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "planner-recovery-20261030/release.py"
SPEC = importlib.util.spec_from_file_location("planner_release_test_target", PATH)
assert SPEC and SPEC.loader
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


def fixture(primary="synthetic-primary", backups="synthetic-one,synthetic-two,synthetic-three"):
    env = {
        "POLARIS_ANALYSIS_API_KEY": primary,
        "POLARIS_ANALYSIS_BASE_URL": "https://api.tengliapi.xyz",
        "POLARIS_ANALYSIS_MODEL": "configured-planner",
        "POLARIS_PROVIDER_FAILOVER_API_KEY": backups,
        "POLARIS_PROVIDER_FAILOVER_BASE_URL": "https://api.ooapi.cc",
        "POLARIS_PROVIDER_FAILOVER_MODEL": "configured-backup-planner",
        "POLARIS_PROVIDER_ROTATION_ORDER": "failover-1,primary",
        "POLARIS_IMAGE_API_KEY": "synthetic-image-only",
    }
    return {"worker": {"Config": {"Env": [key + "=" + value for key, value in env.items()]}}}


class PlannerPolicyTests(unittest.TestCase):
    def test_explicit_primary_order_streaming_and_backups_without_image_keys(self):
        policy = RELEASE.policy(fixture())
        self.assertEqual(set(policy), RELEASE.POLICY_KEYS)
        self.assertEqual(policy["POLARIS_PROVIDER_ROTATION_ORDER"],
                         "primary,failover-1,failover-2,failover-3")
        self.assertEqual(policy["POLARIS_PLANNER_STREAMING_ENABLED"], "true")
        self.assertEqual(policy["POLARIS_PLANNER_RECOVERY_ENABLED"], "true")
        self.assertEqual(policy["POLARIS_PLANNER_TRANSIENT_RETRIES"], "1")
        self.assertNotIn("POLARIS_IMAGE_API_KEY", policy)

    def test_a_joined_pool_cannot_be_used_as_a_single_authorization_key(self):
        with self.assertRaises(AssertionError):
            RELEASE.policy(fixture(primary="synthetic-one,synthetic-two"))

    def test_missing_or_duplicate_backup_keys_stop_configuration(self):
        for keys in ("", "one,two", "one,one,two"):
            with self.subTest(keys=keys), self.assertRaises(AssertionError):
                RELEASE.policy(fixture(backups=keys))
