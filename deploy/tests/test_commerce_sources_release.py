import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "commerce_release", Path(__file__).parents[1] / "release_commerce_sources.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class CommerceReleaseTests(unittest.TestCase):
    def test_prepare_preserves_live_environment_mounts_and_rollback(self):
        def inspect(role):
            return {
                "Id": role, "Image": "sha256:" + "1" * 64,
                "Config": {
                    "Labels": {"com.docker.compose.project.config_files": "/etc/polaris/current.json"},
                    "Env": ["EXISTING_SECRET=value$unchanged"], "Cmd": ["run"], "Entrypoint": None,
                },
                "NetworkSettings": {"Networks": {"production": {"Aliases": [role]}}},
                "Mounts": [{"Type": "volume", "Name": "existing", "Destination": "/app/.data", "RW": True}],
            }

        original = {"services": {role: {"image": "old", "depends_on": ["postgres"], "labels": {"retained": "yes"}} for role in release.SELECTED}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "release"
            key = Path(tmp) / "key"
            key.write_text("ei_test-only")
            with patch.object(release, "inspect", side_effect=inspect), patch.object(release.subprocess, "check_output", return_value=json.dumps(original).encode()), patch.object(release, "compose"):
                release.prepare(root, "sha256:" + "2" * 64, "sha256:" + "3" * 64, key)
            active = json.loads((root / "active.compose.private.json").read_text())
            rollback = json.loads((root / "rollback.compose.private.json").read_text())
            self.assertEqual(set(active["services"]), set(release.SELECTED))
            for role in release.SELECTED:
                self.assertEqual(active["services"][role]["environment"]["EXISTING_SECRET"], "value$$unchanged")
                self.assertEqual(active["services"][role]["volumes"], rollback["services"][role]["volumes"])
                self.assertNotIn("depends_on", active["services"][role])
                self.assertEqual(rollback["services"][role]["image"], "sha256:" + "1" * 64)
            self.assertNotIn("POLARIS_EVERYINFRA_API_KEY", rollback["services"]["replica-api"]["environment"])
            root2 = Path(tmp) / "image-fix"
            with patch.object(release, "inspect", side_effect=inspect), patch.object(release.subprocess, "check_output", return_value=json.dumps(original).encode()), patch.object(release, "compose"):
                release.prepare(root2, "sha256:" + "2" * 64, "sha256:" + "3" * 64, None)
            unchanged_env = json.loads((root2 / "active.compose.private.json").read_text())
            self.assertEqual(unchanged_env["services"]["replica-api"]["environment"], rollback["services"]["replica-api"]["environment"])

    def test_active_api_work_prevents_service_replacement(self):
        with patch.object(release, "unchanged"), patch.object(release, "idle", side_effect=AssertionError("active")), patch.object(release, "compose") as compose:
            with self.assertRaises(AssertionError):
                release.apply(Path("/etc/polaris/commerce-sources-test"))
            compose.assert_not_called()

    def test_health_failure_restores_both_selected_services(self):
        with patch.object(release, "unchanged"), patch.object(release, "idle"), patch.object(release, "health", side_effect=[RuntimeError("unhealthy"), None]), patch.object(release, "compose") as compose:
            with self.assertRaises(RuntimeError):
                release.apply(Path("/etc/polaris/commerce-sources-test"))
            self.assertEqual(compose.call_count, 2)
            self.assertIn("rollback.compose.private.json", str(compose.call_args_list[1].args[0]))
            self.assertEqual(compose.call_args_list[1].args[-2:], release.SELECTED)


if __name__ == "__main__":
    unittest.main()
