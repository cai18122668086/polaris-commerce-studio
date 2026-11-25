"""bihuo-04 e2e (2026-11-25): lipsync video 35 ms shorter than its audio.

The prepared 25 fps suite source had 393 frames for 15.743 s of speech; the
runtime needs round(15.743 * 25) = 394 frames and raised "Media ended before
its planned window". Short tails up to two frames now hold the last frame.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import video_editing_suite_source_hold as hold

# ffprobe of the failed render's suite-source.mp4 (task 8d165f57).
SAVED = {
    "streams": [
        {"codec_type": "video", "avg_frame_rate": "25/1", "nb_frames": "393"},
        {"codec_type": "audio"},
    ]
}


def test_saved_bihuo04_source_is_one_frame_short():
    assert abs(hold.video_shortfall(SAVED, 15.743) - 0.04) < 1e-9


def run_hold(monkeypatch, tmp_path, info, duration):
    calls = []
    monkeypatch.setattr(hold, "probe", lambda path, settings: info)

    def fake_run(command, root, settings, guard, label):
        calls.append(command)
        Path(command[-1]).write_bytes(b"held")

    monkeypatch.setattr(hold, "run", fake_run)
    source = tmp_path / "suite-source.mp4"
    source.write_bytes(b"source")

    class S:
        video_editing_ffmpeg = "ffmpeg"

    return hold.hold_tail(source, duration, tmp_path, S(), None), calls


def test_one_frame_short_is_padded_with_the_last_frame(monkeypatch, tmp_path):
    result, calls = run_hold(monkeypatch, tmp_path, SAVED, 15.743)
    assert result.name == "suite-source-held.mp4"
    assert any(arg.startswith("tpad=stop_mode=clone") for arg in calls[0])
    assert calls[0][calls[0].index("-t") + 1] == "15.743"
    assert (tmp_path / "suite-source-hold.json").is_file()


def test_complete_source_is_used_as_is(monkeypatch, tmp_path):
    full = {"streams": [{**SAVED["streams"][0], "nb_frames": "394"}]}
    result, calls = run_hold(monkeypatch, tmp_path, full, 15.743)
    assert result.name == "suite-source.mp4" and not calls


def test_longer_shortfall_still_fails_strictly(monkeypatch, tmp_path):
    short = {"streams": [{**SAVED["streams"][0], "nb_frames": "390"}]}
    result, calls = run_hold(monkeypatch, tmp_path, short, 15.743)
    assert result.name == "suite-source.mp4" and not calls


def test_24fps_lipsync_clock_is_measured_in_its_own_frames():
    lipsync = {
        "streams": [
            {"codec_type": "video", "avg_frame_rate": "24/1", "nb_frames": "377"}
        ]
    }
    # 377 frames at 24 fps: last frame at 15.667 s, 15.72 s needed -> held.
    assert 0 < hold.video_shortfall(lipsync, 15.743) <= hold.HOLD_FRAMES / 25


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg/ffprobe")
def test_synthetic_24fps_lipsync_reaches_the_suite_frame_count(tmp_path):
    """704x1248 24 fps video 35 ms shorter than its 15.743 s audio."""
    from app.bihuo_suite.source import prepare
    from app.config import Settings
    from app.video_editing_pipeline import probe

    settings = Settings(_env_file=None, video_editing_tasks_dir=tmp_path)
    original = tmp_path / "lipsync.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=704x1248:rate=24:duration=15.708",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=15.743",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(original),
        ],
        check=True,
    )  # fmt: skip
    duration = 15.743
    needed = round(duration * hold.SUITE_FPS)
    prepared = prepare(original, duration, tmp_path, settings, lambda *a, **k: None)
    before = hold.video_shortfall(probe(prepared, settings), duration)
    assert 0 < before <= hold.HOLD_FRAMES / hold.SUITE_FPS  # The e2e failure.
    held = hold.hold_tail(prepared, duration, tmp_path, settings, lambda *a, **k: None)
    info = probe(held, settings)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert int(video["nb_frames"]) >= needed
    assert hold.video_shortfall(info, duration) <= 0
    receipt = json.loads((tmp_path / "suite-source-hold.json").read_text())
    assert receipt["version"] == hold.VERSION
    assert receipt["required_frames"] == needed
