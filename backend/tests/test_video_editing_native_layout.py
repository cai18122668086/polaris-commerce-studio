from copy import deepcopy

import pytest

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_azl_panels import (
    AZL_LAYOUT_INTENT,
    AZL_RECT,
    azl_backing,
    azl_output_bounds,
    verify_azl_layout,
)
from app.video_editing_collage_scene import COLLAGE_SOUNDS, collage_action_frame
from app.video_editing_crowd_scene import crowd_action_frame
from app.video_editing_cxbr import (
    CXBR_CAPTION_INTENT,
    cxbr_entry_frame,
    verify_cxbr_captions,
)
from app.video_editing_native_layout import (
    intentional_role_overlaps,
    projected_scene_end,
    review_with_native_roles,
    verified_effect_groups,
    verify_inset_layout,
)
from app.video_editing_presenter_motion import motion_entry_frame
from app.video_editing_question_card import QUESTION_CARD_A_FONTS
from app.video_editing_unified_scenes import (
    UNIFIED_CAPTION_INTENT,
    split_unified_caption_lanes,
    unified_action_frame,
    verify_unified_captions,
)
from app.video_editing_yy_openings import (
    YY_OPENING_CAPTION_INTENT,
    verify_yy_opening_captions,
    yy_opening_entry_frame,
)


def example():
    shot = {
        "group_id": "SG-S10",
        "layer": "subtitle",
        "start_seconds": 2.5,
        "end_seconds": 5,
        "config": {
            "frame_format": {"fps": 30},
            "frames": 75,
            "events": {"front_start": 20},
        },
    }
    finding = {"shot": 0, "against": "native_roles", "seconds": 2.5 + 42 / 30}
    check = {
        "shot": 0,
        "group_id": "SG-S10",
        "role_review": {
            "role_collisions": [
                {"frame": 42, "roles": ["lead", "accent"], "pixels": 2100}
            ]
        },
    }
    return {"shots": [shot]}, {
        "status": "failed",
        "errors": [finding],
        "subtitle_checks": [check],
    }


def test_documented_backdrop_preserves_original_evidence(tmp_path):
    episode, original_report = example()
    report_path = tmp_path / "layout/review.json"

    def original(data, root, receipts):
        assert data == episode and root == tmp_path and receipts is None
        atomic_json(report_path, original_report)
        raise ValueError(
            "Layout collisions: 1 frame findings; inspect instance layout/review.json"
        )

    review = review_with_native_roles(original, episode, tmp_path, None, {0})
    assert review["status"] == "passed" and review["errors"] == []
    assert review["intentional_role_overlaps"][0]["frame"] == 42
    assert review["original_report_sha256"] == sha256(report_path)
    assert read_json(report_path) == original_report
    assert read_json(tmp_path / "layout/adapter-review.json") == review


@pytest.mark.parametrize(
    "against", ["main_caption", "protected:face", "subtitle:1", "subtitle_safe_rect"]
)
def test_backdrop_does_not_hide_other_collisions(against):
    episode, report = example()
    report["errors"].append({**report["errors"][0], "against": against})
    assert not intentional_role_overlaps(episode, report, {0})


def test_backdrop_requires_opt_in_exact_role_pair_and_foreground_phase():
    episode, report = example()
    assert not intentional_role_overlaps(episode, report, set())
    changed = deepcopy(report)
    changed["subtitle_checks"][0]["role_review"]["role_collisions"][0]["roles"] = [
        "lead",
        "other",
    ]
    assert not intentional_role_overlaps(episode, changed, {0})
    episode["shots"][0]["config"]["events"]["front_start"] = 43
    assert not intentional_role_overlaps(episode, report, {0})


def test_inset_layout_checks_native_caption_ink_and_portrait_duration(tmp_path):
    episode = {
        "output": {"width": 720, "height": 1280},
        "shots": [
            {
                "group_id": "HY-A6",
                "layer": "overlay",
                "rect": [0.15, 0.44, 0.7, 0.40],
                "start_seconds": 1,
                "end_seconds": 3,
            }
        ],
        "captions": [{"start_seconds": 2, "end_seconds": 3}],
        "protected_regions": [
            {"id": "centered-portrait", "start_seconds": 0, "end_seconds": 4}
        ],
    }
    atomic_json(tmp_path / "episode.json", episode)
    atomic_json(tmp_path / "inset-layout-intent.json", {"shots": [0]})
    review = {
        "status": "passed",
        "caption_ink": [{"start": 2, "end": 3, "box": [200, 1100, 500, 1160]}],
    }
    assert (
        verify_inset_layout(tmp_path, review)["insets"][0]["caption_events_checked"]
        == 1
    )
    review["caption_ink"][0]["box"][1] = 1060
    with pytest.raises(ValueError, match="overlaps measured main-caption ink"):
        verify_inset_layout(tmp_path, review)
    episode["protected_regions"][0]["end_seconds"] = 2
    atomic_json(tmp_path / "episode.json", episode)
    with pytest.raises(ValueError, match="speaker keepout for its duration"):
        verify_inset_layout(tmp_path, review)


def test_question_card_allows_only_original_front_overlap():
    episode, report = example()
    shot = episode["shots"][0]
    shot["group_id"] = report["subtitle_checks"][0]["group_id"] = "AH-S03"
    shot["config"] = {
        "fonts": {
            "english": {"path": "input://" + QUESTION_CARD_A_FONTS[0]},
            "question": {"path": "input://" + QUESTION_CARD_A_FONTS[1]},
        },
        "events": {"question_frame": 28, "clear_frame": 46},
    }
    collisions = report["subtitle_checks"][0]["role_review"]["role_collisions"]
    collisions[0]["roles"] = ["english", "question"]
    assert intentional_role_overlaps(episode, report, set(), {0})[0]["frame"] == 42
    assert not intentional_role_overlaps(episode, report, {0})
    bad = deepcopy(report)
    bad["subtitle_checks"][0]["role_review"]["role_collisions"][0]["roles"] = [
        "chinese",
        "question",
    ]
    assert not intentional_role_overlaps(episode, bad, set(), {0})
    bad = deepcopy(report)
    bad["errors"].append({**bad["errors"][0], "against": "main_caption"})
    assert not intentional_role_overlaps(episode, bad, set(), {0})
    shot["config"]["events"]["clear_frame"] = 42
    assert not intentional_role_overlaps(episode, report, set(), {0})


def test_same_place_text_relay_requires_short_original_crossfade():
    episode, report = example()
    shot = episode["shots"][0]
    check = report["subtitle_checks"][0]
    shot["group_id"] = check["group_id"] = "JJ-S06"
    shot["config"] = {"events": {"handoff": [36, 46]}}
    check["role_review"]["role_collisions"][0]["roles"] = ["body", "keyword"]
    assert intentional_role_overlaps(episode, report, set(), handoff_shots={0})
    assert not intentional_role_overlaps(episode, report, set())
    mismatched = deepcopy(report)
    mismatched["errors"].append({**report["errors"][0], "against": "main_caption"})
    assert not intentional_role_overlaps(episode, mismatched, set(), handoff_shots={0})
    mixed_roles = deepcopy(report)
    collisions = mixed_roles["subtitle_checks"][0]["role_review"]["role_collisions"]
    collisions.append({**collisions[0], "roles": ["body", "other"]})
    mixed_roles["errors"].append({**report["errors"][0]})
    assert not intentional_role_overlaps(episode, mixed_roles, set(), handoff_shots={0})
    for span in ([40, 42], [34, 47]):
        shot["config"]["events"]["handoff"] = span
        assert not intentional_role_overlaps(episode, report, set(), handoff_shots={0})


def test_folded_keywords_count_each_original_role_pair_in_the_transition():
    episode, report = example()
    shot = episode["shots"][0]
    check = report["subtitle_checks"][0]
    shot["group_id"] = check["group_id"] = "SG-S04"
    shot["config"] = {
        "events": {"merge_start": 30, "accent_start": 40, "accent_end": 50}
    }
    collisions = check["role_review"]["role_collisions"]
    collisions[0]["roles"] = ["lead_a", "lead_b"]
    collisions.append({**collisions[0], "roles": ["lead_b", "accent"]})
    report["errors"].append({**report["errors"][0]})
    assert (
        len(intentional_role_overlaps(episode, report, set(), progress_shots={0})) == 2
    )
    assert not intentional_role_overlaps(episode, report, set())
    shot["config"]["events"]["accent_start"] = 42
    assert not intentional_role_overlaps(episode, report, set(), progress_shots={0})


def test_split_titles_keep_only_small_contact_after_the_clone_settles():
    episode, report = example()
    shot = episode["shots"][0]
    check = report["subtitle_checks"][0]
    shot["group_id"] = check["group_id"] = "SG-S01"
    shot["config"] = {"events": {"split_end": 34, "detail_start": 37}, "frames": 90}
    overlap = check["role_review"]["role_collisions"][0]
    overlap.update(roles=["main", "detail"], pixels=64)
    assert intentional_role_overlaps(episode, report, set(), progress_shots={0})
    overlap["pixels"] = 65
    assert not intentional_role_overlaps(episode, report, set(), progress_shots={0})


def test_original_foreground_does_not_authorize_white_roles_after_the_join():
    episode, report = example()
    shot = episode["shots"][0]
    check = report["subtitle_checks"][0]
    shot["group_id"] = check["group_id"] = "BG-S10"
    shot["config"] = {
        "events": {"right_frame": 30, "focus_frame": 38, "retreat_frame": 41},
        "frames": 90,
    }
    overlap = check["role_review"]["role_collisions"][0]
    overlap["roles"] = ["right", "focus"]
    assert intentional_role_overlaps(episode, report, set(), progress_shots={0})
    overlap["roles"] = ["left", "right"]
    assert not intentional_role_overlaps(episode, report, set(), progress_shots={0})


def test_original_opening_scene_checks_composed_frame_and_caption_lane(tmp_path):
    shot = {
        "group_id": "YYO05",
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": 3.389,
        "end_seconds": 6.5,
        "config": {"events": {"image_in": 0}},
    }
    assert yy_opening_entry_frame(shot, 30) == 102
    episode = {
        "output": {"height": 1280},
        "shots": [shot],
        "captions": [{"start_seconds": 3.3, "end_seconds": 4.7}],
    }
    atomic_json(tmp_path / "episode.json", episode)
    atomic_json(tmp_path / YY_OPENING_CAPTION_INTENT, {"shots": [0]})
    report = {
        "status": "passed",
        "caption_ink": [{"start": 3.3, "end": 4.7, "box": [120, 1160, 600, 1230]}],
    }
    proof = verify_yy_opening_captions(tmp_path, report)
    assert proof["shots"][0]["smallest_gap_px"] == 40
    report["caption_ink"][0]["box"][1] = 1119
    with pytest.raises(ValueError, match="ink enters"):
        verify_yy_opening_captions(tmp_path, report)


@pytest.mark.parametrize(
    ("group", "start", "events", "expected"),
    [
        ("YYO08", 1.73, {"image_in": 0, "title_in": 16}, 68),
        ("YY6O04", 13.89, {"rectangle": [0, 24]}, 417),
    ],
)
def test_yy_opening_sound_waits_for_the_first_motion_frame(
    group, start, events, expected
):
    shot = {
        "group_id": group,
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": start,
        "config": {"events": events},
    }
    assert yy_opening_entry_frame(shot, 30) == expected


def test_yy6_sound_and_lower_text_use_original_scene_rules(tmp_path):
    shot = {
        "group_id": "YY6O05",
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": 0.41,
        "end_seconds": 4.79,
        "config": {"events": {"flash": [0, 15], "focus": [15, 30]}},
    }
    assert yy_opening_entry_frame(shot, 30, "/events/flash/0") == 13
    assert yy_opening_entry_frame(shot, 30, "/events/focus/0") == 28
    atomic_json(
        tmp_path / "episode.json",
        {
            "output": {"height": 1280},
            "shots": [shot],
            "captions": [{"start_seconds": 0.41, "end_seconds": 2.10}],
        },
    )
    atomic_json(tmp_path / YY_OPENING_CAPTION_INTENT, {"shots": [0]})
    ink = {"start": 0.41, "end": 2.10, "box": [30, 1184, 400, 1264]}
    report = {"status": "passed", "caption_ink": [ink]}
    assert (
        verify_yy_opening_captions(tmp_path, report)["shots"][0]["smallest_gap_px"] == 4
    )
    ink["box"][1] = 1179
    with pytest.raises(ValueError, match="ink enters"):
        verify_yy_opening_captions(tmp_path, report)


def test_original_unified_easing_and_text_band_use_real_output_frames(tmp_path):
    shot = {
        "group_id": "Z-M03",
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": 0.41,
        "end_seconds": 4.79,
        "config": {"timing": {"events": {"title": 0, "item0": 0.30}}},
    }
    assert unified_action_frame(shot, 30, "/timing/events/title") == 13
    assert unified_action_frame(shot, 30, "/timing/events/item0") == 22
    paper = {
        **shot,
        "group_id": "W-R08",
        "start_seconds": 0.4,
        "config": {"timing": {"events": {"cuts": [0, 0.3, 0.65]}}},
    }
    assert unified_action_frame(paper, 30, "/timing/events/cuts/0") == 12
    assert unified_action_frame(paper, 30, "/timing/events/cuts/1") == 21
    atomic_json(
        tmp_path / "episode.json",
        {
            "output": {"height": 1280},
            "shots": [shot],
            "captions": [{"start_seconds": 0.41, "end_seconds": 2.10}],
        },
    )
    atomic_json(tmp_path / UNIFIED_CAPTION_INTENT, {"shots": [0]})
    ink = {"start": 0.41, "end": 2.10, "box": [30, 880, 400, 989]}
    report = {"status": "passed", "caption_ink": [ink]}
    assert verify_unified_captions(tmp_path, report)["shots"][0]["smallest_gap_px"] == 4
    ink["box"][3] = 994
    with pytest.raises(ValueError, match="ink enters"):
        verify_unified_captions(tmp_path, report)
    caption = {"start_seconds": 4.31, "end_seconds": 5.42, "text": "实录字幕"}
    assert split_unified_caption_lanes(
        [caption], [(0.41, 4.79, 980), (4.79, 6, 1257)]
    ) == [
        {**caption, "end_seconds": 4.79},
        {**caption, "start_seconds": 4.79},
    ]


def test_crowd_sound_uses_discrete_original_clock_and_title_ink():
    timing = {
        "duration_seconds": 4.6,
        "events": {
            "paper_exit": 0.4,
            "title_in": 0.66,
            "silhouette_entries": [0.82, 1.0, 1.12, 1.28, 1.38, 1.56, 1.72],
        },
    }
    assert crowd_action_frame(timing, "paper_exit") == 12
    assert crowd_action_frame(timing, "silhouette_entries/0") == 25
    assert crowd_action_frame(timing, "title_in", 10) == 20
    assert crowd_action_frame(timing, "title_in", 12) == 21
    with pytest.raises(ValueError, match="measured original ink"):
        crowd_action_frame(timing, "title_in")


def test_collage_sound_keeps_original_linked_label_clock():
    timing = {
        "duration_seconds": 9.3,
        "events": {
            "layer_entries": [0.28, 1.56, 3.86, 7.70],
            "label_entries": [0.62, 2.22, 2.76, 5.12, 5.12, 8.84, 8.84],
        },
    }
    assert [collage_action_frame(timing, event) for event in COLLAGE_SOUNDS] == [
        9,
        48,
        115,
        240,
    ]


def test_presenter_motion_sound_uses_fixed_and_measured_native_frames():
    shot = {"layer": "scene", "rect": [0, 0, 1, 1]}
    dual = {
        **shot,
        "group_id": "YYP05",
        "start_seconds": 8.65,
        "config": {"events": {"shift_frames": -5}},
    }
    assert motion_entry_frame(dual, 30, "/events/caption_frame") == 286
    reveal = {
        **shot,
        "group_id": "YYP06",
        "start_seconds": 39.11,
        "config": {
            "style": {"geometry": {"camera_start_frame": 20, "reveal_start_frame": 93}}
        },
    }
    assert motion_entry_frame(reveal, 30, "/style/geometry/camera_start_frame") == 1194
    assert motion_entry_frame(reveal, 30, "/style/geometry/reveal_start_frame") == 1267


def test_azl_backing_uses_output_frame_boundaries_and_checks_main_caption_ink(tmp_path):
    shot = {
        "group_id": "AZL01",
        "layer": "scene",
        "rect": list(AZL_RECT),
        "start_seconds": 0.41,
        "end_seconds": 2.24,
        "config": {"events": {"subtitle_in": [0, 8]}},
    }
    episode = {
        "output": {"width": 720, "height": 1280, "fps": 30},
        "source": {"duration_seconds": 3},
        "shots": [shot],
        "captions": [{"start_seconds": 0.41, "end_seconds": 2.24}],
    }
    backing = azl_backing(shot, episode, 0)
    assert backing == {
        "id": "azl-backing-0",
        "start_seconds": 13 / 30,
        "end_seconds": (68 - 1e-5) / 30,
        "background": {"mode": "solid", "color": "#ffffff"},
        "layers": [],
    }
    episode["visual_scenes"] = [backing]
    atomic_json(tmp_path / "episode.json", episode)
    atomic_json(tmp_path / AZL_LAYOUT_INTENT, {"shots": [0]})
    ink = {"start": 0.41, "end": 2.24, "box": [45, 1120, 400, 1240]}
    receipt = {"scene_id": backing["id"], "frames": 55, "fps": 30, "layer_kinds": []}
    delivery = {
        "layout_review": {"status": "passed", "caption_ink": [ink]},
        "visual_scene_receipts": [receipt],
    }
    assert (
        verify_azl_layout(tmp_path, delivery)["shots"][0]["smallest_caption_gap_px"]
        == 40
    )
    ink["box"][1] = 1079
    with pytest.raises(ValueError, match="Main subtitle ink enters"):
        verify_azl_layout(tmp_path, delivery)
    ink["box"][1] = 1120
    receipt["frames"] = 54
    with pytest.raises(ValueError, match="does not cover the panel frames"):
        verify_azl_layout(tmp_path, delivery)


def test_azl_projection_stops_before_original_component_eof():
    shot = {
        "group_id": "AZL03",
        "layer": "scene",
        "rect": list(AZL_RECT),
        "start_seconds": 15.63,
        "end_seconds": projected_scene_end(15.63, 19.05, 103, 30),
        "config": {"events": {"subtitle_in": [0, 8]}},
    }
    assert azl_output_bounds(shot, 30) == (469, 571)
    assert 103 / 30 - (shot["end_seconds"] - shot["start_seconds"]) <= 1 / 30 + 0.0001
    assert projected_scene_end(0.41, 3.59, 96, 30) == 3.59


def test_chenxi_cues_follow_the_original_first_visible_action_and_caption_band(
    tmp_path,
):
    shot = {
        "group_id": "CXBR05",
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": 39.11,
        "end_seconds": 43.11,
        "config": {"timing": {"band_in": 20, "circle_in": 32}},
    }
    assert cxbr_entry_frame(shot, 30, "/timing/band_in") == 1193
    assert cxbr_entry_frame(shot, 30, "/timing/circle_in") == 1206
    atomic_json(
        tmp_path / "episode.json",
        {
            "output": {"height": 1280},
            "shots": [shot],
            "captions": [{"start_seconds": 39.11, "end_seconds": 41.10}],
        },
    )
    atomic_json(tmp_path / CXBR_CAPTION_INTENT, {"shots": [0]})
    ink = {"start": 39.11, "end": 41.10, "box": [30, 1160, 400, 1245]}
    report = {"status": "passed", "caption_ink": [ink]}
    assert verify_cxbr_captions(tmp_path, report)["shots"][0]["smallest_gap_px"] == 190
    ink["box"][1] = 969
    with pytest.raises(ValueError, match="Main caption ink enters"):
        verify_cxbr_captions(tmp_path, report)


def test_preview_counts_decoded_opaque_scenes_and_visible_subtitles():
    subtitles = ("BG-S06", "BG-S03", "SG-S10", "JJ-S03")
    groups = (*subtitles, "YYO01", "YYO01", "Z-M00")
    episode = {
        "output": {"fps": 30},
        "shots": [
            {
                "group_id": group,
                "layer": "subtitle" if group in subtitles else "scene",
                "start_seconds": i,
                "end_seconds": i + 1,
            }
            for i, group in enumerate(groups)
        ],
    }
    delivery = {
        "review": {"encoded_full_decode": True},
        "shots": [
            {
                "group_id": group,
                "decoded": True,
                "encoding": {"full_decode": True, "format": {"frames": 30}},
            }
            for group in groups
        ],
        "layout_review": {
            "status": "passed",
            "subtitle_checks": [
                {"shot": i, "group_id": group, "visible_frames": 20}
                for i, group in enumerate(subtitles)
            ],
        },
    }
    assert verified_effect_groups(episode, delivery) == {*subtitles, "YYO01"}
    delivery["shots"][4]["rgba_sequence"] = "unchecked"
    delivery["shots"][5]["rgba_sequence"] = "unchecked"
    assert verified_effect_groups(episode, delivery) == set(subtitles)
    delivery["layout_review"]["subtitle_checks"][0]["visible_frames"] = 0
    with pytest.raises(ValueError, match="no visible effect"):
        verified_effect_groups(episode, delivery)
