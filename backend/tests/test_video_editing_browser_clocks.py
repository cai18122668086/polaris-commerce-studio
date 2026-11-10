from copy import deepcopy

import pytest

from app import video_editing_browser_clocks as cards
from app import video_editing_browser_rotation as rotation
from app.errors import ApiError
from app.motion_library import atomic_json
from app.video_editing_contracts import SemanticBeat, TranscriptToken
from app.video_editing_overlay_recipes import _browser_split_entry, _rotation_entry
from tests.test_video_editing_native_compiler import inputs


def test_fruit_row_sound_uses_first_original_visible_alpha():
    assert cards.fruit_row_first_frame(20.0) == 22
    assert cards.fruit_row_first_frame(20.94) == 22
    assert cards.fruit_row_first_frame(20.95) == 23


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


def test_rotation_template_binds_each_current_item_before_worker_admission(tmp_path):
    package, transcript, _, _ = inputs(tmp_path)
    group = {
        "id": rotation.ROTATION_GROUP,
        "backend": "browser",
        "input_template": "rotation.json",
        "input_schema": "schema.json",
    }
    atomic_json(
        package / group["input_template"],
        {
            "background": None,
            "presenter": "input://original-demo",
            "duration": 2.4,
            "items": [
                {"label": "旧卡", "at": 0.12 + i, "enter": 0.36, "image": ""}
                for i in range(3)
            ],
        },
    )
    words = (
        ("洗碗", 1000, 1340),
        ("刷锅", 1420, 1700),
        ("洗水果", 2000, 2300),
        ("很方便", 2300, 3000),
    )
    transcript.tokens = [
        TranscriptToken(id=f"t{i}", text=word, start_ms=a, end_ms=b)
        for i, (word, a, b) in enumerate(words)
    ]
    pictures = [f"material-{i}" for i in range(3)]
    beat = SemanticBeat.model_validate(
        {
            "id": "rotation",
            "group_id": group["id"],
            "relation": "parallel",
            "reason": "三项用途逐一轮换。",
            "first_token_id": "t0",
            "last_token_id": "t3",
            "asset_ids": ["source-recorded", *pictures],
            "native_text": [
                {"path": path, "first_token_id": f"t{i}", "last_token_id": f"t{i}"}
                for i, path in enumerate(rotation.ROTATION_LABELS)
            ],
            "native_events": [
                {"path": path, "token_id": f"t{i}", "edge": "start"}
                for i, path in enumerate(rotation.ROTATION_EVENTS)
            ],
            "native_media": [{"path": "/presenter", "asset_id": "source-recorded"}]
            + [
                {"path": path, "asset_id": asset}
                for path, asset in zip(rotation.ROTATION_IMAGES, pictures, strict=True)
            ],
            "relation_items": [
                {
                    "id": f"item-{i}",
                    "first_token_id": f"t{i}",
                    "last_token_id": f"t{i}",
                    "asset_ids": [asset],
                    "native_text_paths": [rotation.ROTATION_LABELS[i]],
                    "native_media_paths": [rotation.ROTATION_IMAGES[i]],
                }
                for i, asset in enumerate(pictures)
            ],
        }
    )
    assets = [
        {
            "id": "source-recorded",
            "kind": "original_video",
            "sha256": transcript.source_sha256,
        }
    ]
    assets.extend(
        {"id": asset, "kind": "image", "sha256": str(i) * 64}
        for i, asset in enumerate(pictures)
    )
    entry, anchors = _rotation_entry(package, group, beat, transcript, assets)
    assert entry.placement.layer == "scene"
    assert entry.recipe["config"]["duration"] == 2
    assert all(item["at"] is None for item in entry.recipe["config"]["items"])
    assert [e["value"] for e in anchors["events"]] == [0, 0.42, 1]
    assets[-1]["sha256"] = assets[-2]["sha256"]
    with pytest.raises(ApiError) as caught:
        _rotation_entry(package, group, beat, transcript, assets)
    assert caught.value.code == "EDITING_TEMPLATE_ROTATION_INPUTS_REQUIRED"


def test_numbered_tags_require_distinct_images_and_each_label_first_word(tmp_path):
    package, transcript, _, _ = inputs(tmp_path)
    group = {
        "id": cards.NUMBERED_GROUP,
        "backend": "browser",
        "input_template": "numbered.json",
        "input_schema": "schema.json",
    }
    atomic_json(
        package / "numbered.json",
        {
            "presenter": "pkg://presenter.svg",
            "background": None,
            "duration": 3,
            "items": [
                {
                    "label": "旧图",
                    "spoken": "原示例",
                    "image": "pkg://sample.svg",
                    "at": i,
                    "enter": 0.38,
                }
                for i in range(3)
            ],
        },
    )
    transcript.tokens = [
        TranscriptToken(
            id=f"t{i}", text=word, start_ms=1000 + i * 600, end_ms=1550 + i * 600
        )
        for i, word in enumerate(("办公", "配件", "小物", "收好"))
    ]
    pictures = [f"material-{i}" for i in range(3)]
    beat = SemanticBeat.model_validate(
        {
            "id": "items",
            "group_id": cards.NUMBERED_GROUP,
            "relation": "parallel",
            "reason": "三种物品各用一图。",
            "first_token_id": "t0",
            "last_token_id": "t3",
            "asset_ids": ["source-recorded", *pictures],
            "native_text": [
                {"path": path, "first_token_id": f"t{i}", "last_token_id": f"t{i}"}
                for i, paths in enumerate(
                    zip(cards.NUMBERED_LABELS, cards.NUMBERED_LINES, strict=True)
                )
                for path in paths
            ],
            "native_events": [
                {"path": path, "token_id": f"t{i}", "edge": "start"}
                for i, path in enumerate(cards.NUMBERED_EVENTS)
            ],
            "native_media": [
                {"path": cards.NUMBERED_PRESENTER, "asset_id": "source-recorded"}
            ]
            + [
                {"path": path, "asset_id": image}
                for path, image in zip(cards.NUMBERED_IMAGES, pictures, strict=True)
            ],
            "relation_items": [
                {
                    "id": f"item-{i}",
                    "first_token_id": f"t{i}",
                    "last_token_id": f"t{i}",
                    "asset_ids": [image],
                    "native_text_paths": [
                        cards.NUMBERED_LABELS[i],
                        cards.NUMBERED_LINES[i],
                    ],
                    "native_media_paths": [cards.NUMBERED_IMAGES[i]],
                }
                for i, image in enumerate(pictures)
            ],
        }
    )
    assets = [
        {
            "id": "source-recorded",
            "kind": "original_video",
            "sha256": transcript.source_sha256,
        },
        *[
            {"id": image, "kind": "image", "sha256": str(i) * 64}
            for i, image in enumerate(pictures)
        ],
    ]
    entry, anchors = _browser_split_entry(package, group, beat, transcript, assets)
    assert (
        entry.placement.layer == "overlay" and entry.recipe["browser_live_background"]
    )
    assert [row["value"] for row in anchors["events"]] == [0, 0.6, 1.2]
    incorrect = beat.model_copy(deep=True)
    incorrect.native_events[1].token_id = "t2"
    duplicate = deepcopy(assets)
    duplicate[-1]["sha256"] = assets[-2]["sha256"]
    for invalid_beat, invalid_assets in ((incorrect, assets), (beat, duplicate)):
        with pytest.raises(ApiError) as caught:
            _browser_split_entry(
                package, group, invalid_beat, transcript, invalid_assets
            )
        assert caught.value.code == "EDITING_TEMPLATE_NUMBERED_INPUTS_REQUIRED"
