"""bihuo-40 (planning 83393be9): a plan without a closing crashed the render.

The host resolves ``quote_start`` to None when there is no closing. Six bundled
runtimes read ``resolved.get("quote_start", duration * k)`` and called
``float(None)`` (TypeError at runtime.py:66, EDITING_INTERNAL_ERROR).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.bihuo_suite import planning, registry
from app.video_editing_contracts import Transcript


def load(name):
    data = json.loads((Path(__file__).parent / "fixtures" / name).read_text("utf-8"))
    return data["plan"], Transcript.model_validate(data["transcript"])


def test_no_closing_reaches_runtime_as_absent_quote_start(monkeypatch):
    seen = {}

    class Runtime:
        @staticmethod
        def compile_request(resolved, **_):
            seen.update(resolved)
            return {"ok": True}

    monkeypatch.setattr(registry, "runtime", lambda _tid: Runtime)
    monkeypatch.setattr(registry, "fonts", lambda _tid: {})
    resolved = {"quote_start": None, "conclusion": None, "captions": []}
    registry.compile_request("bihuo-40-v1", resolved)
    assert "quote_start" not in seen and resolved["quote_start"] is None
    registry.compile_request("bihuo-40-v1", {"quote_start": 12.5})
    assert seen["quote_start"] == 12.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg/ffprobe")
def test_bihuo40_bundled_runtime_compiles_a_plan_without_closing(tmp_path):
    plan, transcript = load("bihuo40_no_closing_plan.json")
    assert plan["conclusion"] is None and plan["quote_start_token_id"] is None
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=gray:size=108x192:rate=25:duration=15.76",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=15.76",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(source),
        ],
        check=True,
    )  # fmt: skip
    resolved = planning.compile_render_input(
        plan, transcript, {}, str(source), {}, recipe_compiler=lambda r, **_: r
    )
    assert resolved["quote_start"] is None
    result = registry.compile_request(
        "bihuo-40-v1", resolved, source_path=str(source), creative_options={}
    )
    config = result["config"]
    assert config["final_start"] == pytest.approx(config["duration"] * 0.84)
    assert len(config["captions"]) == len(plan["captions"])
