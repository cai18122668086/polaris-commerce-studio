"""The avatar upgrade is restricted to the observed video API."""

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def release_module():
    directory = Path(__file__).parents[1] / "video_studio"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(
        "avatar_release", directory / "upgrade_avatar_template.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AvatarReleaseTests(unittest.TestCase):
    def test_prepare_changes_only_video_image_and_server_credential(self):
        release = release_module()
        env = {
            "POLARIS_AUTH_MODE": "external",
            "POLARIS_VIDEO_PROVIDERS_ENABLED": "true",
            "POLARIS_WUYE_API_KEY": "existing$backup",
            "POLARIS_VIDEO_BACKGROUND_RECOVERY_ENABLED": "false",
        }
        live = {
            "Id": "current-video",
            "Image": "sha256:" + "a" * 64,
            "State": {"Health": {"Status": "healthy"}},
            "Config": {"Env": [key + "=" + value for key, value in env.items()]},
        }
        service = {
            "image": live["Image"],
            "environment": env,
            "networks": {"private": {"aliases": ["video-api"]}},
            "volumes": [
                {
                    "type": "volume",
                    "source": "existing-video",
                    "target": "/app/.data/video-studio",
                }
            ],
            "command": ["python", "-m", "uvicorn", "app.main:app"],
        }
        original = copy.deepcopy(service)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "candidate"
            with (
                patch.object(release, "output", return_value=release.NAME.encode()),
                patch.object(release, "inspect", return_value=live),
                patch.object(release, "observed", return_value=copy.deepcopy(service)),
                patch.object(release, "query", return_value="schema-before"),
                patch.object(release, "compose"),
                patch(
                    "sys.stdin",
                    io.StringIO(json.dumps({"POLARIS_YIYUAN_API_KEY": "new$primary"})),
                ),
            ):
                release.prepare(root, "1" * 40, "sha256:" + "b" * 64, live["Image"])
            active = json.loads((root / "active.compose.private.json").read_text())
            rollback = json.loads((root / "rollback.compose.private.json").read_text())
            self.assertEqual(set(active["services"]), {"video-api"})
            current = active["services"]["video-api"]
            self.assertEqual(
                current["environment"]["POLARIS_YIYUAN_API_KEY"], "new$$primary"
            )
            self.assertEqual(
                current["environment"]["POLARIS_WUYE_API_KEY"], "existing$$backup"
            )
            self.assertEqual(
                current["environment"]["POLARIS_VIDEO_BACKGROUND_RECOVERY_ENABLED"],
                "false",
            )
            self.assertEqual(current["volumes"], original["volumes"])
            self.assertEqual(current["networks"], original["networks"])
            self.assertEqual(rollback["services"]["video-api"], original)
            self.assertNotIn(
                "POLARIS_YIYUAN_API_KEY",
                rollback["services"]["video-api"]["environment"],
            )

    def test_busy_video_api_is_not_restarted(self):
        release = release_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(
                json.dumps({"baseline": {release.NAME: {"id": "same"}}})
            )
            with (
                patch.object(release, "inspect", return_value={"Id": "same"}),
                patch.object(release, "query", return_value="1"),
                patch.object(release, "compose") as compose,
                patch.object(release, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "active video"):
                    release.apply(root)
                compose.assert_not_called()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
