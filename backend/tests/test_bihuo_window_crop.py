"""bihuo-window-crop/1: bihuo-02 window crop keeps the face."""

from __future__ import annotations

from types import SimpleNamespace

from app.bihuo_suite import reframe, window_crop
from app.bihuo_suite.registry import runtime

CROP = [0, 420, 1080, 1080]


def test_close_up_face_moves_the_crop_up_with_headroom():
    crop, reason = window_crop.adjusted_crop(CROP, [293, 205, 832, 875])
    assert reason == "moved to keep the face"
    assert crop[1] == 4  # 205 - 0.30 * 670, kept inside the frame
    assert crop[1] <= 205 - 0.10 * 670 and crop[1] + 1080 >= 875
    assert crop[0] == 0 and crop[2:] == [1080, 1080]


def test_face_already_inside_keeps_the_template_crop():
    crop, reason = window_crop.adjusted_crop(CROP, [400, 485, 700, 1024])
    assert crop == CROP and reason == "face already inside the crop"


def test_face_larger_than_the_window_is_centred():
    crop, _ = window_crop.adjusted_crop(CROP, [100, 300, 1000, 1350])
    assert crop[1] == round((300 + 1350) / 2 - 540)


def test_crop_never_leaves_the_frame():
    crop, _ = window_crop.adjusted_crop(CROP, [300, 1500, 700, 1900])
    assert 0 <= crop[1] <= 1920 - 1080


def test_only_the_capsule_template_with_phase2_is_touched(monkeypatch):
    monkeypatch.setattr(
        reframe,
        "measure",
        lambda source, ffmpeg: {
            "samples": 50,
            "found": 50,
            "median_box": [293, 205, 832, 875],
        },
    )
    on = {"frame_policy": {"version": "bihuo-frame/1"}}
    capsule = runtime("bihuo-02-v1")
    payload = {"config": {**on, "raw_crop": list(CROP), "source": "/x.mp4"}}
    with window_crop.execution(capsule, payload) as record:
        assert record["applied"] and payload["config"]["raw_crop"][1] == 4
    assert payload["config"]["raw_crop"] == CROP  # restored afterwards
    for template in ("bihuo-03-v1", "bihuo-04-v1"):
        other = {"config": {**on, "raw_crop": list(CROP), "source": "/x.mp4"}}
        with window_crop.execution(runtime(template), other) as record:
            assert record is None and other["config"]["raw_crop"] == CROP
    off = {"config": {"raw_crop": list(CROP), "source": "/x.mp4"}}
    with window_crop.execution(capsule, off) as record:
        assert record is None


def test_measurement_failure_keeps_the_template_crop(monkeypatch):
    def broken(source, ffmpeg):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(reframe, "measure", broken)
    payload = {
        "config": {
            "frame_policy": {"version": "bihuo-frame/1"},
            "raw_crop": list(CROP),
            "source": "/x.mp4",
        }
    }
    with window_crop.execution(runtime("bihuo-02-v1"), payload) as record:
        assert not record["applied"] and "decode failed" in record["reason"]
        assert payload["config"]["raw_crop"] == CROP
    assert window_crop.execution(SimpleNamespace(), payload).__enter__() is None


def test_crop_stays_out_of_the_reframe_fill_band():
    crop, _ = window_crop.adjusted_crop(CROP, [293, 176, 832, 850], low=254.0)
    assert crop[1] == 254  # never shows synthetic rows above the real picture
    crop, reason = window_crop.adjusted_crop(CROP, [293, 176, 832, 850], low=420.0)
    assert crop == CROP and reason == "no room inside the real picture"
