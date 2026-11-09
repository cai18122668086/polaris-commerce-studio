from copy import deepcopy

import pytest

from app import video_editing_browser_clocks as cards


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
    native["events"][1]["value"] = 20
    with pytest.raises(ValueError, match="distinct ordered frames"):
        cards.compile_card_clock(tmp_path, group, template, config, native)
    native["events"][1]["value"] = 32
    config["cards"][2]["keys"][3][1] = 99
    with pytest.raises(ValueError, match="original card poses"):
        cards.compile_card_clock(tmp_path, group, template, config, native)
