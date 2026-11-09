from copy import deepcopy

import pytest

from app import video_editing_browser_clocks as cards


def test_split_clock_preserves_original_font_and_requires_renderable_items(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        cards,
        "sha256",
        lambda path: {
            "engine.js": cards.SPLIT_ENGINE_SHA,
            "helpers.js": cards.SPLIT_HELPERS_SHA,
            "special.py": cards.SPLIT_WRAPPER_SHA,
        }[path.name],
    )
    config = {
        "duration": 4.0,
        "source_frames": [59, 114],
        "items": [
            {"label": "实录", "at": at, "enter": 0.45} for at in (0.66, 1.08, 1.66)
        ],
    }
    group = {"entry": "engine.js"}
    with pytest.raises(ValueError, match="original browser split title font"):
        cards.compile_split_clock(tmp_path, group, config, {})
    resources = {cards.SPLIT_TITLE_FONT: "fixture-only"}
    receipt = cards.compile_split_clock(tmp_path, group, config, resources)
    assert config["source_frames"] == [0, 119]
    assert receipt["frames"] == 120 and receipt["items"][1]["at"] == 1.08
    config["items"][2]["at"] = 3.54
    with pytest.raises(ValueError, match="settle before export"):
        cards.compile_split_clock(tmp_path, group, config, resources)
    config["items"][2]["at"] = 0.77
    with pytest.raises(ValueError, match="three ordered items"):
        cards.compile_split_clock(tmp_path, group, config, resources)


def test_browser_retimes_shared_poses_and_rejects_invalid_landmarks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        cards,
        "sha256",
        lambda path: (
            cards.CARD_ENGINE_SHA
            if path.name == "engine.js"
            else cards.CARD_TEMPLATE_SHA
        ),
    )
    group = {"entry": "engine.js", "input_template": "config.json"}
    template = {
        "width": 720,
        "height": 1280,
        "fps": 30,
        "frames": 62,
        "cards": [
            {
                "id": card,
                "width": 216,
                "height": 324,
                "keys": [[frame, 1, 2] for frame in frames],
            }
            for card, frames in [
                ("left", [0, 2, 3, 24, 61]),
                ("right", [0, 23, 24, 42, 61]),
                ("middle", [0, 41, 42, 43, 45, 47, 49, 51, 53, 54, 61]),
            ]
        ],
    }
    config = deepcopy(template)
    for card in config["cards"]:
        for key in card["keys"]:
            key[0] = None
    native = {
        "clock": {"start_ms": 39110, "end_ms": 43110, "native_fps": 30},
        "events": [
            {"path": path, "value": value}
            for path, value in zip(cards.CARD_LANDMARKS, (20, 32, 50, 86), strict=True)
        ],
    }
    frames, receipt = cards.compile_card_clock(
        tmp_path, group, template, config, native
    )
    assert receipt["current_landmark_frames"] == [0, 20, 32, 50, 86, 119]
    assert frames["/cards/0/keys/1/0"] == 13.333333
    assert frames["/cards/0/keys/3/0"] == frames["/cards/1/keys/2/0"] == 32
    assert frames["/cards/1/keys/3/0"] == frames["/cards/2/keys/2/0"] == 50
    assert frames["/cards/2/keys/10/0"] == 119
    word_frames, word_receipt = cards.compile_card_clock(
        tmp_path, group, template, config, native, word_entry=True
    )
    assert word_receipt["first_visible_frame_at_word"]
    assert word_frames["/cards/0/keys/1/0"] == 19
    assert word_frames["/cards/0/keys/2/0"] == 20
    native["events"][1]["value"] = 20
    with pytest.raises(ValueError, match="distinct ordered frames"):
        cards.compile_card_clock(tmp_path, group, template, config, native)
    native["events"][1]["value"] = 32
    config["cards"][2]["keys"][3][1] = 99
    with pytest.raises(ValueError, match="original card poses"):
        cards.compile_card_clock(tmp_path, group, template, config, native)
