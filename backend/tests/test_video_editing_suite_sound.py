from app.bihuo_suite.registry import definitions
from app.video_editing_sound_palettes import PALETTES, select_sound
from app.video_editing_suite_actions import SUITE_FAMILIES, suite_actions
from app.video_editing_suite_music import SUITE_MUSIC


def test_every_bihuo_suite_has_a_bounded_sound_palette():
    assert SUITE_FAMILIES.keys() == definitions().keys()
    assert SUITE_MUSIC.keys() == SUITE_FAMILIES.keys()
    sizes = {
        family: len({row[0] for candidates in actions.values() for row in candidates})
        for family, actions in PALETTES.items()
    }
    assert sizes == {"news": 12, "application": 16, "lifestyle": 12}
    cues = [
        select_sound("application", "media", "stable", occurrence)
        for occurrence in range(4)
    ]
    assert len(set(cues[:3])) == 3
    assert cues[0] == cues[3]


def test_native_sound_follows_the_visible_paper_and_picture_clocks():
    paper = suite_actions(
        "bihuo-09-v1",
        {
            "fps": 25,
            "materials": [{"id": "picture"}],
            "phases": [
                {"enabled": True, "entry": [75, 91], "asset_id": "picture"},
                {"enabled": False, "entry": [100, 116], "asset_id": "hidden"},
            ],
        },
    )
    business = suite_actions(
        "bihuo-47-v1",
        {
            "fps": 25,
            "materials": [{"start": 2.0, "visual_start": 3.2}],
            "captions": [{"time": [1.2, 1.8], "lines": [{"emphasis_spans": []}]}],
            "columns": [],
            "star_count": 0,
        },
    )
    assert [at for at, action in paper if action == "media"] == [76 / 25]
    assert [at for at, action in business if action == "media"] == [3.2]
    assert all(action != "emphasis" for _, action in business)
