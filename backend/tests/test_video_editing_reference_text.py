import re

import pytest

from app.video_editing_apple_contracts import AppleSuitePlan, semantic_caption_rows
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_reference_text import caption_boundaries, reconcile_reference


def measured(text):
    # Native character clocks, intentionally missing all reference punctuation.
    units = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+", text)
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=len(units) * 150,
        provider="funasr",
        model="native fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=unit, start_ms=i * 150, end_ms=(i + 1) * 150
            )
            for i, unit in enumerate(units)
        ],
    )


@pytest.mark.parametrize(
    "reference,recognized",
    [
        (
            "商品主图和详情图都检查完成以后，再导出预览，逐张核对。",
            "商品主图和详情图都检查完成以后，再导出预览，主张核对。",
        ),
        (
            "厨房收拾干净以后，再检查水槽和餐具，然后开始洗碗。",
            "厨房收拾干净以后，再检查水槽和餐具，然后开始洗玩。",
        ),
    ],
)
def test_reference_homophones_and_punctuation_recover_before_planning_without_retiming(
    reference, recognized
):
    raw = measured(recognized)
    original = raw.model_dump()
    result, receipt = reconcile_reference(raw, reference, "c" * 64)
    assert receipt["status"] == "applied" and receipt["homophone_changes"] == 1
    assert "".join(t.text for t in result.tokens) == reference
    assert [(t.start_ms, t.end_ms) for t in result.tokens] == [
        (t.start_ms, t.end_ms) for t in raw.tokens
    ]
    assert result.parent_transcript_sha256 == "c" * 64
    assert result.text_status == "automatic" and result.text_revision_id is None
    assert raw.model_dump() == original
    assert set(t.id for t in result.tokens).isdisjoint(t.id for t in raw.tokens)
    assert (
        caption_boundaries(result)["sentence_end_token_ids"][-1] == result.tokens[-1].id
    )


@pytest.mark.parametrize(
    "spoken,reference",
    [
        (
            "先检查商品规格，包装是十二毫升，逐张核对。",
            "先检查商品规格，包装是十五毫升，逐张核对。",
        ),
        (
            "商品图已经准备好了，接下来开始检查。",
            "商品图已经准备好了，接下来立刻开始检查。",
        ),
        (
            "厨房收拾干净以后，再检查水槽和餐具，然后开始洗碗。",
            "厨房收拾干净以后，再检查水槽和餐具，然后开始洗盘。",
        ),
        (
            "准备好商品图片，然后打开OpenAI检查结果。",
            "准备好商品图片，然后打开OpenAB检查结果。",
        ),
    ],
)
def test_reference_cannot_overwrite_different_speech_numbers_names_or_add_words(
    spoken, reference
):
    raw = measured(spoken)
    original = raw.model_dump()
    result, receipt = reconcile_reference(raw, reference, "c" * 64)
    assert receipt["status"] == "skipped" and result is raw
    assert result.model_dump() == original


def test_user_correction_is_not_rewritten_by_automatic_reference_reconciliation():
    raw = measured("商品图先准备好以后，再导出预览主张核对。")
    raw.text_status = "user_corrected"
    result, receipt = reconcile_reference(
        raw, "商品图先准备好以后，再导出预览逐张核对。", "c" * 64
    )
    assert result is raw and receipt["status"] == "skipped"


def plan(captions):
    return AppleSuitePlan.model_validate(
        {
            "opening": {
                "title": {"first_token_id": "unused", "last_token_id": "unused"},
                "subtitle": {"first_token_id": "unused", "last_token_id": "unused"},
                "intro_last_token_id": "unused",
            },
            "body_variant": "points",
            "captions": captions,
        }
    )


def test_caption_cannot_randomly_cut_or_merge_different_reference_sentences():
    reference = "最后看整套图片，颜色和排版是不是统一。检查完成，再导出预览，逐张核对。"
    result, _ = reconcile_reference(measured(reference), reference, "c" * 64)
    end = next(i for i, t in enumerate(result.tokens) if t.text == "版")
    ids = [t.id for t in result.tokens]

    def cue(a, b):
        return {
            "first_token_id": ids[a],
            "last_token_id": ids[b],
            "emphasis": [{"first_token_id": ids[a], "last_token_id": ids[a]}],
        }

    with pytest.raises(ValueError, match="semantic clause boundary"):
        semantic_caption_rows(plan([cue(0, end), cue(end + 1, len(ids) - 1)]), result)
    with pytest.raises(ValueError, match="different sentences"):
        semantic_caption_rows(plan([cue(0, len(ids) - 1)]), result)
    starts = 0
    cues = []
    policy = caption_boundaries(result)
    for i, ident in enumerate(ids):
        if ident in policy["cue_end_token_ids"]:
            cues.append(cue(starts, i))
            starts = i + 1
    rows = semantic_caption_rows(plan(cues), result)
    assert [r["text"] for r in rows] == [
        "最后看整套图片，",
        "颜色和排版是不是统一。",
        "检查完成，",
        "再导出预览，",
        "逐张核对。",
    ]
