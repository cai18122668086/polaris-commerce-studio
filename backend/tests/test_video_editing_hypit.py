import pytest

from app import video_editing_hypit as hypit
from app import video_editing_hypit_strips as strips
from app.config import Settings
from app.motion_library import atomic_json
from app.video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from app.video_editing_word_bindings import word_bindings


def test_hypit_strips_keep_directions_and_bind_entrances_to_words(
    tmp_path, monkeypatch
):
    entry = tmp_path / "scene.svml"
    entry.write_text(
        '<stagger:Entry id="a4m"\n'
        '    items="旧@1,2,3,4>left; 旧@5,6,7,8>right; 旧@9,10,11,12>left"\n'
        '    frames="1,20,30"/>',
        encoding="utf-8",
    )
    special = tmp_path / "commercial_runtime/special.py"
    special.parent.mkdir()
    special.write_text("# Original materializer stand-in")
    monkeypatch.setitem(
        strips.NATIVE_FILES, "commercial_runtime/special.py", strips.sha256(special)
    )
    monkeypatch.setitem(strips.STAGGER_GROUPS, "HY-A4", ("a4m", strips.sha256(entry)))
    group = {"id": "HY-A4", "entry": entry.name}
    native = {
        "clock": {"start_ms": 1000, "end_ms": 5000},
        "text": [
            {"path": path, "text": word, "token_ids": [f"t{i}"]}
            for i, (path, word) in enumerate(
                zip(strips.STRIP_TEXT, ("甲", "乙", "丙"), strict=True)
            )
        ],
        "events": [
            {"path": path, "value": i * 25, "token_id": f"t{i}", "edge": "start"}
            for i, path in enumerate(strips.STRIP_EVENTS)
        ],
        "media": [{"path": strips.STRIP_IMAGE, "asset_id": "stage"}],
    }
    assets = {"stage": {"kind": "image", "source": "project_upload"}}
    data = strips.compile_strips(tmp_path, group, native, assets)
    assert strips._native_attributes(tmp_path, group, data) == {
        "a4m": {
            "items": "甲@1,2,3,4>left; 乙@5,6,7,8>right; 丙@9,10,11,12>left",
            "frames": "0,25,50",
        },
        "t": {"end": "120f"},
    }
    native["events"][1]["token_id"] = "t2"
    with pytest.raises(ValueError, match="spoken label start"):
        strips.compile_strips(tmp_path, group, native, assets)
    native["events"][1]["token_id"] = "t1"
    native["text"][1]["text"] = "乙;frame"
    with pytest.raises(ValueError, match="short labels"):
        strips.compile_strips(tmp_path, group, native, assets)


def test_hypit_price_cards_anchor_numbers_to_distinct_current_images(
    tmp_path, monkeypatch
):
    entry = tmp_path / "price.svml"
    entry.write_text(
        '<stagger:Entry id="a6m"\n'
        '    items="pic3@1,2,3,4>zoom; pic2@5,6,7,8>zoom; pic1@9,10,11,12>zoom"\n'
        '    caps="旧价|99; 旧重|99克; 旧量|99斤" frames="1,20,30"/>',
        encoding="utf-8",
    )
    special = tmp_path / "commercial_runtime/special.py"
    special.parent.mkdir()
    special.write_text("# Original materializer stand-in")
    monkeypatch.setitem(
        strips.NATIVE_FILES, "commercial_runtime/special.py", strips.sha256(special)
    )
    monkeypatch.setitem(strips.STAGGER_GROUPS, "HY-A6", ("a6m", strips.sha256(entry)))
    group = {"id": "HY-A6", "entry": entry.name}
    paths = (strips.STRIP_IMAGE, *strips.CARD_IMAGES)
    native = {
        "clock": {"start_ms": 1000, "end_ms": 5000},
        "text": [
            {"path": path, "text": label, "token_ids": [f"t{i}"]}
            for i, (path, label) in enumerate(
                zip(
                    strips.CARD_TITLES + strips.CARD_DETAILS,
                    ("链接", "每瓶", "两瓶", "14块9", "1000克", "4斤"),
                    strict=True,
                )
            )
        ],
        "events": [
            {"path": path, "value": i * 25, "token_id": f"t{i + 3}", "edge": "start"}
            for i, path in enumerate(strips.CARD_EVENTS)
        ],
        "media": [{"path": path, "asset_id": path} for path in paths],
    }
    assets = {
        path: {"kind": "image", "source": "project_upload", "sha256": str(i)}
        for i, path in enumerate(paths)
    }
    data = strips.compile_strips(tmp_path, group, native, assets)
    assert strips._native_attributes(tmp_path, group, data)["a6m"] == {
        "caps": "链接|14块9; 每瓶|1000克; 两瓶|4斤",
        "frames": "0,25,50",
    }
    bigger = strips.compile_strips(
        tmp_path, group, native, assets, price_card_layout=strips.PRICE_CARD_INSET_TYPE
    )
    assert strips._native_attributes(tmp_path, group, bigger)["a6m"] == {
        "caps": "链接|14块9; 每瓶|1000克; 两瓶|4斤",
        "frames": "0,25,50",
        "cap-size": "96",
        "cap-en-size": "100",
        "cap-dy": "-8",
    }
    native["events"][0]["token_id"] = "t0"
    with pytest.raises(ValueError, match="spoken label start"):
        strips.compile_strips(tmp_path, group, native, assets)
    native["events"][0]["token_id"] = "t3"
    assets[paths[1]]["sha256"] = assets[paths[2]]["sha256"]
    with pytest.raises(ValueError, match="distinct current image bytes"):
        strips.compile_strips(tmp_path, group, native, assets)


def test_hypit_flow_keeps_original_rearrangement_and_checks_source_duration():
    moves = (
        'moves="0:0:208,25,7; 0:19:-220,-37,18; 0:50:12,11,12; '
        '1:24:-584,632,7; 1:51:263,-162,9; 1:61:321,-470,9; 2:52:0,0,9"'
    )
    assert strips._flow_moves(" " + moves, [20, 32, 50], 120) == (
        "0:20:208,25,7; 0:27:-220,-37,18; 0:48:12,11,12; "
        "1:32:-584,632,7; 1:49:263,-162,9; 1:59:321,-470,9; 2:50:0,0,9"
    )
    with pytest.raises(ValueError, match="too little room"):
        strips._flow_moves(" " + moves, [20, 31, 40], 120)
    with pytest.raises(ValueError, match="too little room"):
        strips._flow_moves(" " + moves, [20, 32, 50], 68)

    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=5000,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[],
    )
    native = {
        "clock": {"start_ms": 1000, "end_ms": 5000},
        "media": [{"path": strips.FLOW_PLATE, "asset_id": "source"}],
    }
    assets = {"source": {"kind": "original_video", "sha256": transcript.source_sha256}}
    assert strips.compile_flow_plate(native, assets, transcript)["frames"] == 120
    native["clock"]["start_ms"] = 1001
    with pytest.raises(ValueError, match="actual moving source window"):
        strips.compile_flow_plate(native, assets, transcript)
    native["clock"]["start_ms"] = 1000
    assets["source"]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="actual moving source window"):
        strips.compile_flow_plate(native, assets, transcript)


def test_hypit_slant_cards_keep_three_image_slots_and_native_arrivals(
    tmp_path, monkeypatch
):
    entry = tmp_path / "slant.svml"
    entry.write_text(
        '<stagger:Entry id="a2m" fg="mkfg1@483,1014,597,906"\n'
        ' items="mkpic1@1,2,3,4,7.3>left; mkpic2@5,6,7,8,-4.1>left; '
        'mkpic3@9,10,11,12,5.3>left" caps="旧字" frames="1,20,39"/>',
        encoding="utf-8",
    )
    for name in ("commercial_runtime/special.py", "packages/stagger/dist/render.js"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
        mapping = (
            strips.NATIVE_FILES
            if name.startswith("commercial")
            else strips._FLOW_COMPONENTS
        )
        monkeypatch.setitem(mapping, name, strips.sha256(path))
    monkeypatch.setitem(
        strips.STAGGER_GROUPS, strips.SLANT_GROUP, ("a2m", strips.sha256(entry))
    )
    group = {"id": strips.SLANT_GROUP, "entry": entry.name}
    paths = (strips.SLANT_BACKGROUND, strips.SLANT_FOREGROUND, *strips.SLANT_IMAGES)
    names = ("洗碗", "刷锅", "洗水果")
    native = {
        "clock": {"start_ms": 1000, "end_ms": 5000},
        "text": [
            {"path": path, "text": label, "token_ids": [f"t{i}"]}
            for i, (path, label) in enumerate(
                zip(strips.STRIP_TEXT, names, strict=True)
            )
        ],
        "events": [
            {"path": path, "value": frame, "token_id": f"t{i}", "edge": "start"}
            for i, (path, frame) in enumerate(
                zip(strips.STRIP_EVENTS, (20, 32, 50), strict=True)
            )
        ],
        "media": [{"path": path, "asset_id": path} for path in paths],
        "media_clocks": [{"media_path": strips.SLANT_FOREGROUND, "frames": 120}],
    }
    assets = {
        path: {"kind": "image", "source": "project_upload", "sha256": str(i)}
        for i, path in enumerate(paths)
    }
    assets[strips.SLANT_FOREGROUND]["kind"] = "original_video"
    glosses = [
        {"source_text": a, "display_text": b}
        for a, b in zip(names, ("DISHES", "PANS", "FRUIT"), strict=True)
    ]
    data = strips.compile_strips(tmp_path, group, native, assets, slant_glosses=glosses)
    assert strips._native_attributes(tmp_path, group, data)["a2m"] == {
        "caps": "洗碗|DISHES; 刷锅|PANS; 洗水果|FRUIT",
        "fg": "",
        "frames": "20,32,50",
    }
    assert strips.stagger_audio_frame(strips.SLANT_GROUP, 20) == 21
    glosses[0]["source_text"] = "刷锅"
    with pytest.raises(ValueError, match="its own spoken title"):
        strips.compile_strips(tmp_path, group, native, assets, slant_glosses=glosses)
    assets[strips.SLANT_IMAGES[0]]["sha256"] = assets[strips.SLANT_IMAGES[1]]["sha256"]
    with pytest.raises(ValueError, match="distinct current image bytes"):
        strips.compile_strips(tmp_path, group, native, assets)


def test_hypit_sound_anchor_requires_the_rendered_scene_entry(tmp_path):
    stem = "001-HY-A6"
    sidecar = tmp_path / "hypit-strips" / f"{stem}.json"
    atomic_json(sidecar, {"group_id": "HY-A6", "entry_frames": [10, 20, 30]})
    work = tmp_path / "hypit-strips" / "work" / stem
    scene = work / "hypit/HY-A6/scene.svml"
    scene.parent.mkdir(parents=True)
    scene.write_text('<stagger:Entry id="a6m" items="picture>zoom" frames="10,20,30"/>')
    receipt = work / "tengli-strip-materialization.json"
    ref = {
        "group_id": "HY-A6",
        "shot": stem,
        "sidecar_sha256": strips.sha256(sidecar),
        "index": 1,
        "frame": 20,
        "audible_frame": 21,
    }
    atomic_json(
        receipt,
        {"sidecar_sha256": ref["sidecar_sha256"], "scene_sha256": strips.sha256(scene)},
    )
    strips.verify_stagger_entry(tmp_path, ref)
    scene.write_text('<stagger:Entry id="a6m" items="picture>zoom" frames="10,21,30"/>')
    atomic_json(
        receipt,
        {"sidecar_sha256": ref["sidecar_sha256"], "scene_sha256": strips.sha256(scene)},
    )
    with pytest.raises(ValueError, match="entry frames differ"):
        strips.verify_stagger_entry(tmp_path, ref)


def test_hypit_tools_only_for_the_configured_internal_workspace(tmp_path, monkeypatch):
    module = tmp_path / "hypit" / "bin" / "hypit.mjs"
    module.parent.mkdir(parents=True)
    module.write_bytes(b"audited fixture")
    (module.parent.parent / "package.json").write_text('{"version":"0.2.12"}')
    chrome = tmp_path / "chrome"
    chrome.touch()
    settings = Settings(
        environment="test",
        auth_mode="development",
        video_editing_hypit_internal_workspace="internal",
        video_editing_hypit_local_module=module,
        video_editing_hypit_local_chrome=chrome,
    )
    monkeypatch.setattr(hypit, "CLI_SHA256", hypit.sha256(module))
    assert hypit.hypit_tools(settings, "internal")["hypit_module"] == str(module)
    for unavailable, workspace in (
        (settings, "external-workspace"),
        (settings.model_copy(update={"environment": "production"}), "internal"),
        (settings.model_copy(update={"auth_mode": "external"}), "internal"),
        (Settings(), "internal"),
    ):
        with pytest.raises(ValueError, match="internal development workspace"):
            hypit.hypit_tools(unavailable, workspace)
    module.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        hypit.hypit_tools(settings, "internal")


def test_hypit_uses_real_source_windows_and_keeps_each_image_on_its_word(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(hypit, "NATIVE_FILES", {})
    tokens = [
        TranscriptToken(
            id=f"t{i}", text=word, start_ms=1000 + i * 1000, end_ms=2000 + i * 1000
        )
        for i, word in enumerate(("甲", "乙", "丙"))
    ]
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=4100,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=tokens,
    )
    asset_ids = ["source", "p0", "p1", "p2"]
    media_paths = ["/background/path", *hypit.PICTURE_PATHS]
    beat = SemanticBeat.model_validate(
        {
            "id": "triad",
            "first_token_id": "t0",
            "last_token_id": "t2",
            "group_id": hypit.PICTURE_GROUP,
            "relation": "parallel",
            "reason": "三项同级并列",
            "asset_ids": asset_ids,
            "native_events": [
                {"path": path, "token_id": t.id, "edge": "start"}
                for path, t in zip(hypit.ENTRY_PATHS, tokens, strict=True)
            ],
            "native_media": [
                {"path": path, "asset_id": a}
                for path, a in zip(media_paths, asset_ids, strict=True)
            ],
            "relation_items": [
                {
                    "id": a,
                    "first_token_id": t.id,
                    "last_token_id": t.id,
                    "asset_ids": [a],
                    "native_media_paths": [path],
                }
                for a, t, path in zip(
                    asset_ids[1:], tokens, hypit.PICTURE_PATHS, strict=True
                )
            ],
        }
    )
    contract = {
        "group_id": hypit.PICTURE_GROUP,
        "native_fps": 30,
        "text_paths": [],
        "event_paths": [{"path": path, "unit": "frames"} for path in hypit.ENTRY_PATHS],
        "resource_paths": [{"path": path} for path in media_paths],
    }
    bindings = word_bindings(beat, transcript, contract, set(asset_ids))
    assets = {
        "source": {"kind": "original_video", "sha256": transcript.source_sha256},
        **{
            a: {"kind": "image", "source": "project_upload", "sha256": a}
            for a in asset_ids[1:]
        },
    }
    config = {"enter_frames": 10}
    starts, receipts = hypit.compile_picture_clocks(
        tmp_path, config, bindings, assets, transcript, beat
    )
    assert starts == {"/background/start_seconds": 1.0}
    assert receipts[0]["source_end_ms"] == 4000
    assert [row["value"] for row in bindings["events"]] == [0, 30, 60]
    wrong = beat.model_copy(
        update={"relation_items": list(reversed(beat.relation_items))}
    )
    with pytest.raises(ValueError, match="its own spoken relation item"):
        hypit.compile_picture_clocks(
            tmp_path, config, bindings, assets, transcript, wrong
        )
    with pytest.raises(ValueError, match="reading interval"):
        hypit.compile_picture_clocks(
            tmp_path, {"enter_frames": 30}, bindings, assets, transcript, beat
        )
    assets["p2"]["sha256"] = assets["p1"]["sha256"]
    with pytest.raises(ValueError, match="three distinct"):
        hypit.compile_picture_clocks(
            tmp_path, config, bindings, assets, transcript, beat
        )


def test_full_canvas_keeps_strip_directions_and_card_anchors():
    strips_before = (
        "甲@31,386,654,111>wipe-right; 乙@447,736,602,111>wipe-right; "
        "丙@14,1094,618,111>wipe-left"
    )
    assert strips._live_stage_items(strips_before, price_cards=False) == (
        "甲@31,851,654,111>wipe-right; 乙@447,1201,602,111>wipe-right; "
        "丙@14,1559,618,111>wipe-left"
    )
    cards_before = (
        "mka6c3@45,1239,938,271>zoom; mka6c2@45,851,938,271>zoom; "
        "mka6c1@45,475,938,271>zoom"
    )
    assert strips._live_stage_items(cards_before, price_cards=True) == (
        "mka6c3@45,1420,938,238>zoom; mka6c2@45,1148,938,238>zoom; "
        "mka6c1@45,876,938,238>zoom"
    )
