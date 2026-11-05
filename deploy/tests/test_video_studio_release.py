import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "video_studio/prepare.py"
spec = importlib.util.spec_from_file_location("video_prepare", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CADDY = "www.tengliapi.xyz {\n\trequest_body {\n\t\tmax_size 25MB\n\t}\n\thandle @api {\n\t\thandle { reverse_proxy api:8000 }\n\t}\n}\napi.tengliapi.xyz { reverse_proxy upstream:3000 }\npay.tengliapi.xyz { reverse_proxy payments:80 }\n"

class VideoReleaseTests(unittest.TestCase):
    def test_video_route_preserves_existing_sites_and_body_limits(self):
        result = module.caddy_with_video(CADDY)
        self.assertEqual(result.split("api.tengliapi.xyz", 1)[1], CADDY.split("api.tengliapi.xyz", 1)[1])
        self.assertIn("path /api/v1/video-studio/*", result)
        self.assertIn("not path /api/v1/video-studio/*", result)
        self.assertIn("max_size 55MB", result)
        self.assertIn("max_size 25MB", result)
        self.assertIn("reverse_proxy api:8000", result)
        with self.assertRaises(ValueError): module.caddy_with_video(result)
        with self.assertRaises(ValueError): module.caddy_with_video("unexpected")

    def test_prepare_isolates_video_preserves_networks_and_keeps_credentials_private(self):
        revision = "a" * 40
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "release/deploy").mkdir(parents=True)
            old_caddy = root / "old.Caddyfile"; old_caddy.write_text(CADDY)
            real_path = Path
            def mapped(value):
                value = str(value)
                if value.startswith("/etc/polaris/video-studio-"): return root / "control"
                if value == "/opt/polaris/releases": return root / "release-parent"
                return real_path(value)
            (root / "release-parent" / revision / "deploy").mkdir(parents=True)
            live = {}; configs = {}
            for role in ["api", "frontend", "caddy"]:
                mounts = [{"Type":"bind","Source":str(old_caddy),"Destination":"/etc/caddy/Caddyfile","RW":False}] if role == "caddy" else []
                live[role] = {"Id":role+"-before","Image":"sha256:"+"1"*64,"Config":{"Labels":{"com.docker.compose.service":role,"com.docker.compose.project.config_files":"/private/"+role},"Env":["SECRET=keep$this", "POLARIS_AUTH_MODE=external"],"Cmd":["run"],"Entrypoint":None},"NetworkSettings":{"Networks":{"edge":{"Aliases":[role]},"payments":{"Aliases":[role]}}},"Mounts":mounts}
                configs["/private/"+role] = {"services":{role:{"read_only":True,"cap_drop":["ALL"],"security_opt":["no-new-privileges:true"],"environment":{},"networks":{},"depends_on":{"api":{}}}}}
            expected = {"services":{role:{"image":value["Image"]} for role,value in live.items()}}
            def output(args): return json.dumps(configs[args[3]]).encode()
            with patch.object(module, "Path", side_effect=mapped), patch.object(module, "inspect", side_effect=lambda role:live[role]), patch.object(module.subprocess,"check_output",side_effect=output), patch.object(module.subprocess,"run"):
                module.prepare(revision,"sha256:"+"2"*64,"sha256:"+"3"*64,{"POLARIS_VIDEO_COSYVOICE_ENABLED":"true","POLARIS_VIDEO_COSYVOICE_API_KEY":"fixture-only"},expected)
            active = json.loads((root/"control/active.compose.private.json").read_text())
            self.assertEqual(set(active["services"]), {"video-api","frontend","caddy"})
            video = active["services"]["video-api"]
            self.assertTrue(video["read_only"]);self.assertEqual(video["cap_drop"],["ALL"])
            self.assertNotIn("ports",video)
            self.assertTrue(all(value["aliases"] == ["video-api"] for value in video["networks"].values()))
            self.assertEqual(video["environment"]["POLARIS_AUTH_MODE"],"external")
            self.assertEqual(video["environment"]["POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED"],"false")
            self.assertEqual(video["environment"]["SECRET"],"keep$$this")
            self.assertEqual(len(video["volumes"]),1)
            self.assertIn("payments",active["services"]["caddy"]["networks"])
            before = json.loads((root/"control/rollback.compose.private.json").read_text())
            self.assertEqual(before["services"]["frontend"]["image"],live["frontend"]["Image"])
            self.assertEqual(before["services"]["caddy"]["volumes"][0]["source"],str(old_caddy))
            self.assertIn("SECRET=keep$this",(root/"control/runtime.env").read_text())

if __name__ == "__main__": unittest.main()
