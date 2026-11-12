import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from app.video_editing_apple_contracts import (
    ENGINE,
    TEMPLATE_ID,
    build_request,
    bundle_identity,
    compile_render_input,
    verify_plan,
)
from app.video_editing_contracts import Transcript, TranscriptToken, TranscriptUtterance


def transcript():
    words = [
        "我们",
        "展示",
        "商品图",
        "先",
        "复制",
        "商品链接",
        "再",
        "上传",
        "产品图",
        "节省",
        "时间",
        "保持",
        "风格",
        "让",
        "商品",
        "更清楚",
        "现在",
        "开始",
    ]
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=18000,
        provider="fixture",
        model="measured",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"w{i}", text=text, start_ms=i * 1000, end_ms=(i + 1) * 1000
            )
            for i, text in enumerate(words)
        ],
        utterances=[
            TranscriptUtterance(
                id=f"u{i}",
                text="".join(words[i * 3 : i * 3 + 3]),
                token_ids=[f"w{n}" for n in range(i * 3, i * 3 + 3)],
                start_ms=i * 3000,
                end_ms=(i + 1) * 3000,
            )
            for i in range(6)
        ],
    )


def span(first, last=None):
    return {
        "first_token_id": f"w{first}",
        "last_token_id": f"w{first if last is None else last}",
    }


def cards():
    # Deliberately reverse the spoken order; retrieval must use descriptions.
    return [
        {
            "id": "photo",
            "kind": "image",
            "sha256": "c" * 64,
            "viewed_identity": "上传实拍图",
            "semantic_use": "上传自己的产品照片",
        },
        {
            "id": "link",
            "kind": "video",
            "sha256": "d" * 64,
            "viewed_identity": "复制商品链接",
            "semantic_use": "商品链接复制操作录屏",
            "duration_ms": 3000,
        },
        {
            "id": "unrelated",
            "kind": "image",
            "sha256": "e" * 64,
            "viewed_identity": "海边日落",
            "semantic_use": "旅游风景",
        },
    ]


def plan():
    return {
        "opening": {
            "title": span(1, 2),
            "subtitle": span(0, 2),
            "intro_last_token_id": "w2",
        },
        "body_variant": "materials",
        "materials": [
            {**span(3, 5), "asset_id": "link", "show_at_token_id": "w5", "edge": "end"},
            {
                **span(6, 8),
                "asset_id": "photo",
                "show_at_token_id": "w8",
                "edge": "end",
            },
        ],
        "points": [],
        "features": [span(11, 12)],
        "conclusion": {"first": span(13, 15), "second": span(16, 17)},
        "quote_start_token_id": "w13",
        "chapters": [{**span(3, 5), "at_token_id": "w2"}],
        "emphasis": [span(7, 8)],
    }


def test_full_script_request_matches_named_materials_before_any_render():
    body, evidence = build_request(transcript(), "fixture-model", cards())
    payload = json.loads(body["messages"][1]["content"])
    assert len(payload["transcript"]["tokens"]) == 18
    assert payload["transcript"]["tokens"][-1]["text"] == "开始"
    assert payload["template"]["id"] == TEMPLATE_ID
    matches = {
        row["material_id"]: row
        for row in payload["material_sentence_alignment"]["materials"]
    }
    assert matches["link"]["candidates"][0]["id"] == "u1"
    assert matches["photo"]["candidates"][0]["id"] == "u2"
    assert matches["unrelated"]["status"] == "unmatched"
    assert "不可信数据" in body["messages"][0]["content"]
    assert "禁止逐帧视觉API" in body["messages"][0]["content"]
    expected = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    assert evidence["request_sha256"] == hashlib.sha256(expected).hexdigest()
    assert evidence["request_bytes"] == len(expected)
    assert evidence["catalog_group_count"] == 8


def test_short_tail_word_cannot_be_used_as_the_whole_opening():
    value = transcript()
    value.duration_ms //= 10
    for token in value.tokens:
        token.start_ms //= 10
        token.end_ms //= 10
    for utterance in value.utterances:
        utterance.start_ms //= 10
        utterance.end_ms //= 10
    with pytest.raises(ValueError, match="at least1.6"):
        verify_plan(plan(), value, cards())


@pytest.mark.parametrize(
    "mutation,message",
    [
        (
            lambda p: p["opening"]["title"].update(first_token_id="invented"),
            "Unknown recorded word",
        ),
        (lambda p: p["materials"].reverse(), "speech order"),
        (
            lambda p: p["materials"][0].update(asset_id="invented"),
            "Unknown or unsupported",
        ),
        (lambda p: p["materials"][1].update(asset_id="link"), "must not repeat"),
        (lambda p: p["materials"][0].update(show_at_token_id="w0"), "matched phrase"),
        (lambda p: p["opening"].update(intro_last_token_id="w6"), "after opening"),
        (lambda p: p.update(quote_start_token_id="w5"), "before quote"),
        (lambda p: p["materials"][0].update(path="C:/outside.mp4"), "Extra inputs"),
    ],
)
def test_invalid_word_ids_materials_and_placement_order_fail_closed(mutation, message):
    raw = plan()
    mutation(raw)
    with pytest.raises(ValueError, match=message):
        verify_plan(raw, transcript(), cards())


def test_no_material_or_conclusion_is_required_when_script_does_not_support_it():
    raw = plan()
    raw.update(materials=[], features=[], conclusion=None, quote_start_token_id=None)
    result = verify_plan(raw, transcript(), cards())
    assert result["materials"] == [] and result["conclusion"] is None
    raw["quote_start_token_id"] = "w13"
    with pytest.raises(ValueError, match="present together"):
        verify_plan(raw, transcript(), cards())


def test_points_capacity_and_source_order_are_enforced():
    raw = plan()
    raw.update(
        body_variant="points",
        materials=[],
        points=[span(3, 5), span(6, 8), span(9, 10), span(11, 12)],
        features=[],
    )
    with pytest.raises(ValueError, match="at most 3"):
        verify_plan(raw, transcript(), cards())
    raw["points"] = [span(6, 8), span(3, 5)]
    with pytest.raises(ValueError, match="source order"):
        verify_plan(raw, transcript(), cards())


def test_compile_uses_real_word_times_and_owner_files_without_changing_voice_clock(
    tmp_path, monkeypatch
):
    assets = {}
    for card in cards():
        file = tmp_path / (card["id"] + ".media")
        file.write_bytes(b"fixture")
        assets[card["id"]] = {**card, "path": str(file)}
    captured = {}

    def recipe(resolved, **kwargs):
        captured.update(resolved=resolved, kwargs=kwargs)
        return {"source": kwargs["source_path"], "duration": resolved["duration"]}

    monkeypatch.setitem(
        sys.modules, "app.apple_minimal.recipes", SimpleNamespace(compile_recipe=recipe)
    )
    result = compile_render_input(
        plan(),
        transcript(),
        assets,
        "actual-original.media",
        {},
        creative_options={
            "title": "  自填主题  ",
            "name_card": {"enabled": False, "name": "隐藏名字"},
        },
        music="off",
    )
    assert result == {"source": "actual-original.media", "duration": 18}
    resolved = captured["resolved"]
    assert resolved["title"] == "自填主题"
    assert resolved["opening_end"] == 3
    assert [(r["asset_id"], r["start"], r["end"]) for r in resolved["materials"]] == [
        ("link", 6, 9),
        ("photo", 9, 11),
    ]
    assert resolved["materials"][0]["path"] == assets["link"]["path"]
    assert resolved["materials"][0]["spoken_text"] == "先复制商品链接"
    assert captured["kwargs"]["music"] == "off"
    assert captured["kwargs"]["creative_options"]["name_card"]["enabled"] is False
    assert all(
        len(row["text"]) <= 16 and row["time"][1] - row["time"][0] <= 3
        for row in resolved["captions"]
    )
    assert "".join(row["text"] for row in resolved["captions"]) == "".join(
        t.text for t in transcript().tokens
    )
    assert any(row["emphasis"] == "上传产品图" for row in resolved["captions"])


def test_real_recipe_accepts_resolved_contract_without_provider_or_ffmpeg(tmp_path):
    # This checks the actual integration surface; no billed model or renderer call.
    assets = {}
    for card in cards():
        file = tmp_path / (card["id"] + ".media")
        file.write_bytes(b"fixture")
        assets[card["id"]] = {**card, "path": str(file)}
    try:
        import app.apple_minimal.recipes  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("root runtime package is still being assembled")
    result = compile_render_input(
        plan(),
        transcript(),
        assets,
        "original.media",
        {
            "main": "fixture-font",
            "support": "fixture-font",
            "caption": "fixture-font",
            "caption_bold": "fixture-font",
        },
    )
    assert result["source"] == "original.media"
    assert result["duration"] == 18
    assert result["fps"] == 25
    assert result["media"]


def test_bundle_identity_tracks_actual_python_source():
    identity = bundle_identity()
    assert identity["engine"] == ENGINE
    assert len(identity["sha256"]) == 64
    assert identity == bundle_identity()
