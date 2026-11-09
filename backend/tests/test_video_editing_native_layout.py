from copy import deepcopy

import pytest

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_native_layout import (
    intentional_role_overlaps,
    review_with_native_roles,
    verify_inset_layout,
)
from app.video_editing_question_card import QUESTION_CARD_A_FONTS


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
    for span in ([40, 42], [34, 47]):
        shot["config"]["events"]["handoff"] = span
        assert not intentional_role_overlaps(episode, report, set(), handoff_shots={0})
