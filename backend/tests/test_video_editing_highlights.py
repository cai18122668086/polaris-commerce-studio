"""User highlight selections only retime the targeted native text role."""

import pytest

from app.video_editing_contracts import (
    NativeHighlightEdit,
    NativeRenderEdits,
    SemanticPlan,
    Transcript,
    TranscriptToken,
)
from app.video_editing_highlights import (
    AUTOMATIC_TEXT_PROFILE,
    apply_highlight_edits,
    highlight_targets,
)


def fixture():
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=5000,
        provider="test_annotation",
        model="timed-word-fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=text, start_ms=i * 600, end_ms=(i + 1) * 600
            )
            for i, text in enumerate(
                ("日常", "洗碗", "刷锅、", "洗水果、", "洗蔬菜", "不能", "一斤")
            )
        ],
    )
    plan = SemanticPlan.model_validate(
        {
            "audience_question": "如何使用",
            "argument_outline": ["用途"],
            "style_reason": "原生并列词",
            "beats": [
                {
                    "id": "uses",
                    "first_token_id": "t0",
                    "last_token_id": "t6",
                    "group_id": "BG-S04",
                    "relation": "explanation",
                    "reason": "用途",
                    "native_text": [
                        {
                            "path": "/content/body",
                            "first_token_id": "t1",
                            "last_token_id": "t1",
                            "punctuation": "omit_sentence_punctuation",
                        },
                        {
                            "path": "/content/focus",
                            "first_token_id": "t2",
                            "last_token_id": "t2",
                            "punctuation": "omit_sentence_punctuation",
                        },
                    ],
                    "native_events": [
                        {
                            "path": "/events/body_frame",
                            "token_id": "t1",
                            "edge": "start",
                        },
                        {
                            "path": "/events/focus_frame",
                            "token_id": "t2",
                            "edge": "start",
                        },
                    ],
                }
            ],
        }
    )
    recipe = {
        "entries": {
            "uses": {
                "placement": {"layer": "subtitle"},
                "recipe": {
                    "design_id": AUTOMATIC_TEXT_PROFILE,
                    "group_id": "BG-S04",
                    "placeholders": [
                        "/content/body",
                        "/content/focus",
                        "/events/body_frame",
                        "/events/focus_frame",
                    ],
                },
            },
        },
    }
    return plan, recipe, transcript


def test_highlight_changes_one_original_role_and_keeps_its_source_span():
    plan, recipe, transcript = fixture()
    focus = next(
        t
        for t in highlight_targets(plan, recipe, transcript)
        if t.path == "/content/focus"
    )
    assert focus.current_text == "刷锅"
    assert [row.text for row in focus.options] == ["洗水果", "洗蔬菜"]
    edit = NativeHighlightEdit(
        beat_id="uses",
        path="/content/focus",
        first_token_id="t3",
        last_token_id="t3",
    )
    original = plan.model_dump_json()
    effective, receipts = apply_highlight_edits([edit], plan, recipe, transcript)
    assert plan.model_dump_json() == original
    before, after = plan.beats[0], effective.beats[0]
    assert (before.first_token_id, before.last_token_id) == (
        after.first_token_id,
        after.last_token_id,
    )
    assert (
        after.native_text[0] == before.native_text[0]
        and after.native_events[0] == before.native_events[0]
    )
    assert (
        after.native_text[1].first_token_id == after.native_events[1].token_id == "t3"
    )
    assert receipts[0]["applied_text"] == "洗水果"
    assert receipts[0]["locked_by_user"] and receipts[0]["start_ms"] == 1800


def test_highlight_rejects_protected_text_wrong_slot_and_conflicting_edit():
    plan, recipe, transcript = fixture()
    selection = dict(
        beat_id="uses", path="/content/focus", first_token_id="t3", last_token_id="t3"
    )
    edit = NativeHighlightEdit(**selection)
    for change in (
        {"path": "/events/focus_frame"},
        {"first_token_id": "t5", "last_token_id": "t5"},
        {"first_token_id": "t6", "last_token_id": "t6"},
        {"last_token_id": "other-transcript"},
        {"beat_id": "other-segment"},
    ):
        with pytest.raises(ValueError):
            apply_highlight_edits(
                [NativeHighlightEdit(**{**selection, **change})],
                plan,
                recipe,
                transcript,
            )
    with pytest.raises(ValueError):
        NativeRenderEdits(highlight_edits=[edit, edit])
    with pytest.raises(ValueError):
        NativeRenderEdits(source_only_beat_ids=["uses"], highlight_edits=[edit])
    assert NativeRenderEdits(music="off").model_dump(mode="json") == {
        "music": "off",
        "source_only_beat_ids": [],
    }
