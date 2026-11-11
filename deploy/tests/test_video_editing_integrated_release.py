"""Video-only topology and authentication checks before any Docker mutation."""

import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def module():
    file = Path(__file__).parents[1] / "video_studio/integrated_release.py"
    spec = importlib.util.spec_from_file_location("integrated_video_release", file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class IntegratedVideoReleaseTests(unittest.TestCase):
    def test_preparation_preserves_auth_other_services_and_native_media(self):
        release = module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            caddy = parent / "Caddyfile.current"
            caddy.write_text(
                "@video_request path /api/v1/video-studio/*\n"
                "request_body @video_request {\n max_size 55MB\n}\n"
                "reverse_proxy video-api:8000\n"
            )
            env = {
                "POLARIS_AUTH_MODE": "supertokens",
                "POLARIS_VIDEO_MEDIA_DIR": "/app/.data/video-studio",
                "POLARIS_CELERY_BROKER_URL": "redis://redis:6379/0",
                "POLARIS_CELERY_RESULT_BACKEND": "redis://redis:6379/1",
                "POLARIS_WUYE_API_KEY": "synthetic$a",
                "POLARIS_QUANYU_API_KEY": "synthetic$b",
                "POLARIS_TAO_API_KEY": "synthetic$c",
                "POLARIS_VIDEO_SCRIPT_API_KEY": "synthetic$d",
            }
            live = {
                role: {
                    "Id": role + "-old",
                    "Image": "sha256:" + "a" * 64,
                    "State": {"Health": {"Status": "healthy"}},
                    "Config": {
                        "Env": [key + "=" + value for key, value in env.items()]
                    },
                }
                for role in (*release.ROLES, "api")
            }
            baseline = copy.deepcopy(live)

            def observed(item):
                mounts = [
                    {
                        "type": "volume",
                        "source": "existing-video",
                        "target": "/app/.data/video-studio",
                        "read_only": False,
                    }
                ]
                if item["Id"] == "caddy-old":
                    mounts = [
                        {
                            "type": "bind",
                            "source": str(caddy),
                            "target": "/etc/caddy/Caddyfile",
                            "read_only": True,
                        }
                    ]
                return {
                    "image": item["Image"],
                    "networks": {"existing-private": {"aliases": [item["Id"]]}},
                    "volumes": mounts,
                }

            root = parent / "candidate"
            names = [release.PROJECT + "-" + role + "-1" for role in live]
            with (
                patch.object(release, "output", return_value=" ".join(names).encode()),
                patch.object(
                    release,
                    "inspect",
                    side_effect=lambda name: live[
                        name.removeprefix(release.PROJECT + "-").removesuffix("-1")
                    ],
                ),
                patch.object(release, "observed", side_effect=observed),
                patch.object(release, "compose"),
                patch("sys.stdin", io.StringIO("{}")),
            ):
                release.prepare(
                    root,
                    "1" * 40,
                    parent / "assets",
                    "sha256:" + "b" * 64,
                    "sha256:" + "c" * 64,
                )
            result = json.loads((root / "active.compose.private.json").read_text())
            services = result["services"]
            self.assertEqual(
                set(services),
                {
                    "video-api",
                    "frontend",
                    "caddy",
                    "editing-worker",
                    "editing-maintenance",
                },
            )
            self.assertEqual(live, baseline)
            self.assertEqual(
                services["video-api"]["environment"]["POLARIS_AUTH_MODE"], "supertokens"
            )
            self.assertEqual(
                services["video-api"]["environment"]["POLARIS_WUYE_API_KEY"],
                "synthetic$$a",
            )
            self.assertTrue(
                all("ports" not in service for service in services.values())
            )
            worker = services["editing-worker"]
            self.assertEqual(
                worker["networks"]["existing-private"]["aliases"], ["editing-worker"]
            )
            self.assertTrue(
                next(
                    row
                    for row in worker["volumes"]
                    if row["source"] == "existing-video"
                )["read_only"]
            )
            self.assertEqual(
                worker["environment"]["POLARIS_VIDEO_EDITING_ENABLED"], "true"
            )
            self.assertIn("--queues=editing,editing-planning", worker["command"])
            self.assertIn("max_size 55MB", caddy.read_text())
            self.assertIn("max_size 210MB", (root / "Caddyfile").read_text())
            rollback = json.loads((root / "rollback.compose.private.json").read_text())
            self.assertEqual(set(rollback["services"]), set(release.ROLES))


if __name__ == "__main__":
    unittest.main()
