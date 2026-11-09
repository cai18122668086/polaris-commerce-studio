from copy import deepcopy

import pytest

from app import video_editing_browser_clocks as cards
from app import video_editing_browser_rotation as rotation
from tests.test_video_editing_native_compiler import inputs


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


def test_rotation_binds_spoken_focuses_and_a_moving_presenter(tmp_path, monkeypatch):
    package, transcript, _, _ = inputs(tmp_path)
    monkeypatch.setattr(rotation, "_audit", lambda *_: None)
    group = {"id": rotation.ROTATION_GROUP}
    config = {
        "duration": 3.34,
        "background": None,
        "items": [
            {"label": label, "at": at, "enter": 0.36}
            for label, at in (("洗碗", 0), ("刷锅", 0.42), ("洗水果", 1))
        ],
    }
    slots = [f"/items/{i}" for i in range(3)]
    native = {
        "clock": {"start_ms": 1000, "end_ms": 4340, "native_fps": 30},
        "events": [
            {"path": slot + "/at", "edge": "start", "token_id": f"t{i}"}
            for i, slot in enumerate(slots)
        ],
        "text": [
            {"path": slot + "/label", "token_ids": [f"t{i}"]}
            for i, slot in enumerate(slots)
        ],
        "media": [{"path": "/presenter", "asset_id": "source"}]
        + [{"path": slot + "/image", "asset_id": slot} for slot in slots],
    }
    assets = {"source": {"kind": "original_video", "sha256": transcript.source_sha256}}
    assets.update(
        {
            slot: {"kind": "image", "source": "project_upload", "sha256": str(i)}
            for i, slot in enumerate(slots)
        }
    )
    resources = {
        key: "fixture" for key in (*cards.FRUIT_LIST_FONTS, rotation.ROTATION_MATTE)
    }
    proof = rotation.rotation_source_clock(native, assets, transcript)
    assert proof["source_start_ms"] == 1000 and proof["source_end_ms"] == 4340
    result = rotation.compile_rotation_clock(
        package, group, config, resources, native, assets
    )
    assert result["first_motion_frames"] == [0, 13, 31]
    assert result["frames"] == 100
    shot = {
        "group_id": rotation.ROTATION_GROUP,
        "layer": "scene",
        "start_seconds": 39.77,
        "config": config,
    }
    assert [
        rotation.rotation_entry_frame(shot, 30, path)
        for path in rotation.ROTATION_EVENTS
    ] == [1194, 1206, 1224]
    config["items"][0]["at"] = 0.1
    with pytest.raises(ValueError, match="first card starts"):
        rotation.compile_rotation_clock(
            package, group, config, resources, native, assets
        )
    config["items"][0]["at"] = 0
    assets[slots[2]]["sha256"] = assets[slots[0]]["sha256"]
    with pytest.raises(ValueError, match="distinct current pictures"):
        rotation.compile_rotation_clock(
            package, group, config, resources, native, assets
        )
    assets["source"]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="current, measured presenter"):
        rotation.rotation_source_clock(native, assets, transcript)
