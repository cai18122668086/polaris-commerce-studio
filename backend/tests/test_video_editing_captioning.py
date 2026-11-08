"""Annotated text/timing boundaries, not recognition or real-media acceptance."""

import copy

import pytest

from app.video_editing_captioning import segmentation_metadata
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_pipeline import EditingFailure, caption_rows


def annotation(text):
    return Transcript(
        source_sha256="b" * 64,
        audio_sha256="a" * 64,
        duration_ms=len(text) * 100 + 1000,
        provider="boundary fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=char, start_ms=100 + i * 100, end_ms=200 + i * 100
            )
            for i, char in enumerate(text)
        ],
    )


def assert_preserved(transcript, rows):
    tokens = {t.id: t for t in transcript.tokens}
    assert [tid for row in rows for tid in row["token_ids"]] == [
        t.id for t in transcript.tokens
    ]
    for row in rows:
        actual = [tokens[tid] for tid in row["token_ids"]]
        assert row["text"] == "".join(t.text for t in actual).strip()
        assert row["start_seconds"] == actual[0].start_ms / 1000
        assert row["end_seconds"] == actual[-1].end_ms / 1000


def test_current_price_brand_and_unit_clauses_never_start_with_stranded_eight():
    text = "终于等到14块9到手，两大瓶，火力二十八，柠檬洗洁精了，"
    transcript = annotation(text)
    original = copy.deepcopy(transcript)
    rows = caption_rows(transcript)
    assert [r["text"] for r in rows] == [
        "终于等到14块9到手，",
        "两大瓶，",
        "火力二十八，",
        "柠檬洗洁精了，",
    ]
    assert_preserved(transcript, rows)
    assert transcript == original


def test_long_clause_balances_at_lexical_token_boundaries_without_tiny_suffix():
    transcript = annotation("你们谁之前花十几块钱买一瓶的那真是亏大发了呀。")
    rows = caption_rows(transcript)
    assert len(rows) == 2
    assert all(4 <= len(r["text"]) <= 20 for r in rows)
    assert any("十几块钱" in r["text"] for r in rows)
    assert any("一瓶" in r["text"] for r in rows)
    assert any("真是" in r["text"] for r in rows)
    assert_preserved(transcript, rows)


def test_decimal_thousands_price_ratio_and_ascii_grade_remain_complete():
    transcript = annotation(
        "价格14.9元，规格1,000克，价格14块9，比例1:100，符合A类标准。"
    )
    rows = caption_rows(transcript)
    for phrase in ("14.9元", "1,000克", "14块9", "1:100", "A类"):
        assert any(phrase in r["text"] for r in rows)
    assert_preserved(transcript, rows)
    assert not any(r["text"].startswith(("，", ",", ".", ":", "类")) for r in rows)


def test_real_pause_closes_a_clause_without_inventing_a_hold_or_new_clock():
    transcript = annotation("我喜欢这个产品")
    for token in transcript.tokens[3:]:
        token.start_ms += 700
        token.end_ms += 700
    rows = caption_rows(transcript)
    assert rows[0]["text"] == "我喜欢"
    assert rows[0]["end_seconds"] == 0.4
    assert rows[1]["start_seconds"] == 1.1
    assert_preserved(transcript, rows)


def test_parallel_list_comma_does_not_create_a_flashing_single_item():
    transcript = annotation("日常用它来洗碗、刷锅、洗水果、蔬菜啥的都老放心了。")
    rows = caption_rows(transcript)
    assert len(rows) == 2
    assert not any(row["text"] in {"刷锅、", "洗水果、"} for row in rows)
    assert rows[0]["text"].endswith("、")
    assert any("洗水果" in row["text"] for row in rows)
    assert all(len(row["text"]) >= 4 for row in rows)
    assert_preserved(transcript, rows)


@pytest.mark.parametrize(
    "text", ["1234567890123456789012345元", "averylonguninterruptedproductidentifier"]
)
def test_oversized_number_or_word_requires_review_instead_of_time_splitting(text):
    with pytest.raises(EditingFailure) as error:
        caption_rows(annotation(text))
    assert error.value.code == "EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED"


def test_a_single_asr_token_is_never_split_into_fake_subword_times():
    transcript = annotation("这是一个边界测试")
    transcript.tokens = [
        TranscriptToken(
            id="whole",
            text="这是一条超过二十字但只有一个实际识别时间区间的口播记录。",
            start_ms=100,
            end_ms=800,
        )
    ]
    with pytest.raises(EditingFailure) as error:
        caption_rows(transcript)
    assert error.value.code == "EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED"


def test_dictionary_identity_and_review_scope_are_explicit():
    metadata = segmentation_metadata()
    assert metadata["tokenizer"] == "jieba/0.42.1; HMM=False"
    assert (
        metadata["dictionary_sha256"]
        == "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8"
    )
    assert metadata["semantic_review"] == metadata["visual_review"] == "unreviewed"
    assert not metadata["spoken_tokens_changed"]
