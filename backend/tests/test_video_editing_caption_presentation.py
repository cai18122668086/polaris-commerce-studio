import copy

import pytest

from app.motion_library import atomic_json
from app.video_editing_caption_presentation import (
    bridge_scene_gaps,
    native_clock_shot,
    readable_caption_rows,
    remove_duplicate_captions,
    reserve_caption_lane,
    verify_reserved_caption_lane,
)
from app.video_editing_contracts import Transcript, TranscriptToken


def transcript(text, pause_at=None, gap=300):
    tokens = [
        TranscriptToken(
            id=f"w{i}", text=c, start_ms=100 + i * 150, end_ms=250 + i * 150
        )
        for i, c in enumerate(text)
    ]
    if pause_at is not None:
        for token in tokens[pause_at:]:
            token.start_ms += gap
            token.end_ms += gap
    return Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=tokens[-1].end_ms + 1000,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=tokens,
        utterances=[],
    )


def test_display_holds_and_short_clause_merge_preserve_every_word_and_clock():
    source = transcript("有参考，做复刻；先看14块9，再核对商品信息。", 10)
    before = copy.deepcopy(source)
    rows = readable_caption_rows(source)
    assert rows[0]["text"] == "有参考，做复刻；"
    assert [key for row in rows for key in row["token_ids"]] == [
        token.id for token in source.tokens
    ]
    assert any("14块9" in row["text"] for row in rows)
    for row, following in zip(rows, rows[1:], strict=False):
        assert row["end_seconds"] <= following["start_seconds"]
        if following["start_seconds"] - row["speech_end_seconds"] <= 0.8:
            assert row["end_seconds"] == following["start_seconds"]
    assert source == before


def test_long_silence_is_not_filled_with_stale_caption():
    source = transcript("先看商品。再看结果。", 5, 1800)
    rows = readable_caption_rows(source)
    assert rows[1]["start_seconds"] - rows[0]["end_seconds"] > 1.5


def test_native_replacement_waits_for_actual_entry_and_keeps_extra_spoken_words():
    anchors = [
        {
            "text": "这四个入口不是四种商品。",
            "start_seconds": 2,
            "end_seconds": 4.2,
            "speech_end_seconds": 4,
        }
    ]
    shot = {
        "group_id": "LYO01",
        "start_seconds": 2,
        "end_seconds": 4,
        "config": {
            "content": {"caption": "这四个入口不是四种商品"},
            "events": {"text_frame": 6},
        },
    }
    episode = {"shots": [shot], "captions": copy.deepcopy(anchors)}
    removed = remove_duplicate_captions(episode, anchors)
    assert removed[0]["start_seconds"] == 2.2
    assert [
        (row["start_seconds"], row["end_seconds"]) for row in episode["captions"]
    ] == [(2, 2.2), (4, 4.2)]
    episode["captions"] = copy.deepcopy(anchors)
    shot["config"]["content"]["caption"] = "四个入口"
    assert remove_duplicate_captions(episode, anchors) == []
    assert episode["captions"] == anchors


def test_adjacent_chapters_continue_presenter_without_moving_word_events():
    first = {
        "group_id": "Z-M15",
        "layer": "scene",
        "start_seconds": 0.21,
        "end_seconds": 3.63,
        "config": {
            "timing": {"duration_seconds": 3.42, "events": {"title": 1.2}},
            "media": {
                "presenter": {
                    "kind": "video",
                    "offset_seconds": 0.21,
                    "duration_seconds": 3.42,
                }
            },
        },
    }
    second = {**copy.deepcopy(first), "start_seconds": 4.03, "end_seconds": 8.43}
    episode = {"shots": [first, second], "source": {"duration_seconds": 10}}
    changes = bridge_scene_gaps(episode)
    assert changes and first["end_seconds"] == 4.03
    assert first["config"]["media"]["presenter"]["offset_seconds"] == 0.21
    assert first["config"]["timing"]["events"] == {"title": 1.2}
    second["start_seconds"] = 5
    first["end_seconds"] = 3.63
    assert bridge_scene_gaps(episode) == []


def test_real_ink_must_fit_above_platform_margin_and_below_native_scene(tmp_path):
    episode = {
        "shots": [
            {
                "group_id": "Z-M15",
                "layer": "scene",
                "start_seconds": 0,
                "end_seconds": 3,
                "rect": [0, 0, 1, 1],
            }
        ],
        "captions": [{"text": "完整条件保留", "start_seconds": 0, "end_seconds": 3}],
        "source": {"duration_seconds": 3},
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "typography": {
            "caption": {
                "size_px": 72,
                "baseline_y_px": 1886,
                "layout_overrides": [{"baseline_y_px": 1900}],
            }
        },
        "visual_scenes": [],
        "editorial": {},
    }
    reserve_caption_lane(episode, [], [])
    assert episode["typography"]["caption"]["baseline_y_px"] == 1613
    assert "layout_overrides" not in episode["typography"]["caption"]
    assert episode["shots"][0]["rect"][3] < 0.79
    atomic_json(tmp_path / "episode.json", episode)
    report = {
        "status": "passed",
        "caption_ink": [{"start": 0, "end": 3, "box": [100, 1550, 980, 1620]}],
    }
    assert verify_reserved_caption_lane(tmp_path, report, [0])["status"] == "passed"
    report["caption_ink"][0]["box"][1] = 500
    with pytest.raises(ValueError, match="overlaps"):
        verify_reserved_caption_lane(tmp_path, report, [0])
    report["caption_ink"][0]["box"] = [100, 1550, 980, 1850]
    with pytest.raises(ValueError, match="platform margin"):
        verify_reserved_caption_lane(tmp_path, report, [0])


def test_existing_panel_headroom_is_not_scaled_twice_and_native_owner_stays_full():
    episode = {
        "shots": [
            {
                "group_id": "AZL01",
                "layer": "scene",
                "start_seconds": 0,
                "end_seconds": 2,
                "rect": [0, 0, 1, 0.84375],
            },
            {
                "group_id": "LYO01",
                "layer": "scene",
                "start_seconds": 2,
                "end_seconds": 4,
                "rect": [0, 0, 1, 1],
            },
        ],
        "captions": [{"text": "读区", "start_seconds": 0, "end_seconds": 2}],
        "source": {"duration_seconds": 4},
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "typography": {"caption": {"size_px": 72}},
        "visual_scenes": [],
        "editorial": {},
    }
    result = reserve_caption_lane(episode, [], [])
    assert episode["shots"][0]["rect"][3] == result["scene_area_bottom_ratio"]
    assert episode["shots"][1]["rect"] == [0, 0, 1, 1]
    assert native_clock_shot(episode, 0)["rect"] == [0, 0, 1, 0.84375]
    assert native_clock_shot(episode, 0)["start_seconds"] == 0
