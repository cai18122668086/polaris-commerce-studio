"""bihuo-reframe/1: one static vertical shift when the face is far off."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.bihuo_suite import reframe


def measured(box, found=50, samples=50):
    return {"samples": samples, "found": found, "median_box": list(box)}


def test_face_inside_the_band_is_left_alone():
    assert reframe.shift_for(measured((446, 338, 755, 735))) == 0


def test_high_face_moves_down_to_the_reference_centre():
    shift = reframe.shift_for(measured((403, 12, 783, 477)))
    assert shift == 296
    assert shift % 2 == 0


def test_low_face_moves_up_and_shift_is_capped():
    shift = reframe.shift_for(measured((400, 1300, 700, 1700)))
    assert shift == -reframe.MAX_SHIFT


def test_unreliable_detection_does_not_reframe():
    assert reframe.shift_for(measured((403, 12, 783, 477), found=10)) == 0
    assert reframe.shift_for({"samples": 0, "found": 0}) == 0


def test_filter_graph_keeps_full_frame_size():
    down = reframe.filter_graph(296)
    assert "crop=1080:1624:0:0" in down and "[e][m]vstack" in down
    up = reframe.filter_graph(-120)
    assert "crop=1080:1800:0:120" in up and "[m][e]vstack" in up


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_prepare_skips_without_a_face_and_writes_a_receipt(tmp_path):
    source = tmp_path / "flat.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=1080x1920:r=25:d=1",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    settings = SimpleNamespace(video_editing_ffmpeg="ffmpeg")
    path, receipt = reframe.prepare(source, tmp_path, settings, lambda: None)
    assert path == source
    assert receipt["applied"] is False
    assert (tmp_path / "suite-source-reframe.json").is_file()
