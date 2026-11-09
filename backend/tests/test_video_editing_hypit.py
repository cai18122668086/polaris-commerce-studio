import pytest

from app import video_editing_hypit as hypit
from app import video_editing_hypit_strips as strips
from app.config import Settings
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
    monkeypatch.setitem(strips.STRIP_GROUPS, "HY-A4", ("a4m", strips.sha256(entry)))
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
