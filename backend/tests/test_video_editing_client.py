import hashlib
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from fetch_video_editing_handoff import fetch_handoff  # noqa: E402


@pytest.mark.parametrize("failure", [None, "digest", "external_path"])
def test_editor_download_verifies_materials_and_never_forwards_grant(tmp_path, failure):
    handoff = str(uuid4())
    prefix = f"/api/v1/video-studio/editing-handoffs/{handoff}"
    materials = {
        "video": b"mp4-fixture",
        "audio": b"mp3-fixture",
        "script": "确认稿".encode(),
    }
    manifest = {
        "files": {
            "video": "talking-head.mp4",
            "audio": "narration.mp3",
            "script": "confirmed-script.txt",
        },
        "assets": {kind: prefix + "/assets/" + kind for kind in materials},
        "script_sha256": hashlib.sha256(materials["script"]).hexdigest(),
        **{
            kind + "_format": {"sha256": hashlib.sha256(materials[kind]).hexdigest()}
            for kind in ["video", "audio"]
        },
    }
    if failure == "external_path":
        manifest["assets"]["video"] = "https://other.invalid/steal"
    if failure == "digest":
        manifest["video_format"]["sha256"] = "0" * 64
    requests = []

    def server(request):
        requests.append(request)
        assert request.url.host == "editor-api.example"
        assert request.headers["Authorization"] == "Bearer fixture"
        if request.url.path.endswith("/manifest"):
            return httpx.Response(200, json=manifest)
        return httpx.Response(
            200, content=materials[request.url.path.rsplit("/", 1)[-1]]
        )

    def call():
        return fetch_handoff(
            "https://editor-api.example",
            handoff,
            "fixture",
            tmp_path,
            transport=httpx.MockTransport(server),
        )
    if failure:
        with pytest.raises(ValueError):
            call()
        assert not list(tmp_path.rglob("*.part"))
        assert not list(tmp_path.rglob("manifest.json"))
        assert len(requests) == (1 if failure == "external_path" else 2)
    else:
        folder = call()
        for kind, data in materials.items():
            assert (folder / manifest["files"][kind]).read_bytes() == data
        assert "fixture" not in (folder / "manifest.json").read_text(encoding="utf-8")
