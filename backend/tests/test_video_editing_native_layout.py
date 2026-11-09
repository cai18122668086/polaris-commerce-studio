from copy import deepcopy

import pytest

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_native_layout import backdrop_role_overlaps, review_with_backdrop


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

    review = review_with_backdrop(original, episode, tmp_path, None, {0})
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
    assert not backdrop_role_overlaps(episode, report, {0})


def test_backdrop_requires_opt_in_exact_role_pair_and_foreground_phase():
    episode, report = example()
    assert not backdrop_role_overlaps(episode, report, set())
    changed = deepcopy(report)
    changed["subtitle_checks"][0]["role_review"]["role_collisions"][0]["roles"] = [
        "lead",
        "other",
    ]
    assert not backdrop_role_overlaps(episode, changed, {0})
    episode["shots"][0]["config"]["events"]["front_start"] = 43
    assert not backdrop_role_overlaps(episode, report, {0})
