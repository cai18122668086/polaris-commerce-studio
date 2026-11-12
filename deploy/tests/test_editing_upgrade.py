import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def load():
    folder = Path(__file__).parents[1] / "video_studio"
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("editing_upgrade", folder / "upgrade_editing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EditingUpgradeTests(unittest.TestCase):
    def test_upgrade_retains_auth_secrets_queues_and_data_mounts(self):
        module = load()
        original = {
            "image": "old", "environment": {"AUTH": "synthetic$$secret"},
            "networks": {"private": {}}, "read_only": True,
            "volumes": [
                {"type": "bind", "source": "/old-examples", "target": "/template-examples", "read_only": True},
                {"type": "volume", "source": "live-data", "target": "/app/.data", "read_only": False},
            ],
            "command": ["worker", "editing,editing-planning"],
        }
        live = {module.name(role): {"Config": {"Env": ["POLARIS_AUTH_MODE=external", "POLARIS_VIDEO_EDITING_ALIGNMENT_ENABLED=true"]}} for role in module.ROLES}
        baseline = copy.deepcopy(live)
        images = {role: "new-" + role for role in module.ROLES}
        with patch.object(module, "observed", side_effect=lambda _: copy.deepcopy(original)):
            active, rollback = module.services_for(live, images, "a"*40, Path("/new-examples"))
        self.assertEqual(live, baseline)
        self.assertEqual(set(active["services"]), set(module.ROLES))
        self.assertNotIn("caddy", active["services"])
        for role, service in active["services"].items():
            self.assertEqual(service["environment"], original["environment"])
            self.assertEqual(service["command"], original["command"])
            self.assertEqual(service["volumes"][1], original["volumes"][1])
            self.assertEqual(rollback["services"][role], original)
            self.assertEqual(service["image"], images[role])
            expected = "/old-examples" if role == "frontend" else str(Path("/new-examples"))
            self.assertEqual(service["volumes"][0]["source"], expected)

    def test_active_work_blocks_cutover_without_modifying_jobs(self):
        module = load()
        with patch.object(module, "query", return_value="1") as query:
            with self.assertRaisesRegex(ValueError, "Active work"):
                module.require_idle()
        self.assertTrue(query.call_args.args[0].startswith("select count(*)"))

    def test_invalid_alignment_setup_fails_before_compose_mutation(self):
        module = load()
        live = {module.name(role): {"Config": {"Env": ["POLARIS_AUTH_MODE=external"]}} for role in module.ROLES}
        with patch.object(module, "observed", return_value={"volumes": [], "networks": {}}):
            with self.assertRaisesRegex(ValueError, "alignment"):
                module.services_for(live, {role:"new" for role in module.ROLES}, "a"*40, Path("/examples"))
