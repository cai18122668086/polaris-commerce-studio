from copy import deepcopy

import pytest

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_native_layout import (
    intentional_role_overlaps,
    review_with_native_roles,
    verified_effect_groups,
    verify_inset_layout,
)
from app.video_editing_presenter_motion import motion_entry_frame
from app.video_editing_question_card import QUESTION_CARD_A_FONTS
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
