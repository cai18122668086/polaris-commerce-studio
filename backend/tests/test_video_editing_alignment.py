from copy import deepcopy
from pathlib import Path

import pytest

from app.video_editing_alignment import normalize_alignment
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_pipeline import EditingFailure


def evidence():
    parent = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=2000,
        provider="funasr",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(id="t0", text="洗", start_ms=200, end_ms=500),
            TranscriptToken(id="t1", text="玩。", start_ms=500, end_ms=900),
        ],
    )
    prepared = {
        "audio_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "duration_ms": 2000,
        "clock": {"audio_offset_ms": 0},
    }
    return parent, prepared


def normalize(result, text, parent, prepared):
    return normalize_alignment(
        result,
        text,
        prepared,
        parent,
        "c" * 64,
        "candidate-one",
        "operator_candidate",
        Path("pinned-model"),
        "d" * 64,
        "1.4.24",
    )


def test_correction_gets_new_actual_alignment_without_rewriting_parent_or_review():
    parent, prepared = evidence()
    original = parent.model_dump()
    result = [{"text": "洗 碗", "timestamp": [[100, 400], [400, 700]]}]
    aligned = normalize(result, "洗碗。", parent, prepared)
    assert parent.model_dump() == original
    assert "".join(t.text for t in aligned.tokens) == "洗碗。"
    assert aligned.tokens[0].start_ms == 100  # Not the old ASR clock at 200.
    assert aligned.tokens[-1].end_ms == 700
    assert aligned.tokens[0].id != parent.tokens[0].id
    assert aligned.utterances[0].token_ids == [t.id for t in aligned.tokens]
    assert aligned.parent_transcript_sha256 == "c" * 64
    assert aligned.provider == "funasr-fa-zh"
    assert aligned.text_status == "operator_candidate"
    assert aligned.timing_review == "unreviewed"


@pytest.mark.parametrize(
    "result",
    [
        [{"text": "洗", "timestamp": [[100, 700]]}],
        [{"text": "洗 玩", "timestamp": [[100, 400], [400, 700]]}],
        [{"text": "洗 碗", "timestamp": [[100, 400]]}],
        [{"text": "洗 碗", "timestamp": [[100, 600], [400, 700]]}],
        [{"text": "洗 碗", "timestamp": [[100, 400], [400, 2100]]}],
        [{"text": "洗 碗"}],
    ],
)
def test_mismatched_words_missing_or_invalid_clocks_are_never_repaired(result):
    parent, prepared = evidence()
    with pytest.raises(EditingFailure):
        normalize(result, "洗碗。", parent, prepared)


def test_input_casing_and_punctuation_remain_separate_from_native_model_text():
    parent, prepared = evidence()
    result = [
        {
            "text": "a 类 洗 碗",
            "timestamp": [[100, 300], [300, 500], [600, 800], [800, 1000]],
        }
    ]
    aligned = normalize(result, "A类；洗碗。", parent, prepared)
    assert "".join(t.text for t in aligned.tokens) == "A类；洗碗。"
    assert len(aligned.utterances) == 2
    wrong_source = deepcopy(prepared)
    wrong_source["audio_sha256"] = "0" * 64
    with pytest.raises(EditingFailure) as error:
        normalize(result, "A类；洗碗。", parent, wrong_source)
    assert error.value.code == "EDITING_ALIGNMENT_SOURCE_MISMATCH"


def test_numeric_subtokens_join_measured_bounds_without_guessing_character_time():
    parent, prepared = evidence()
    result = [
        {
            "text": "1 4 9 元",
            "timestamp": [[100, 200], [200, 350], [400, 500], [500, 700]],
        }
    ]
    aligned = normalize(result, "14.9元。", parent, prepared)
    assert "".join(t.text for t in aligned.tokens) == "14.9元。"
    assert aligned.tokens[0].start_ms == 100
    assert aligned.tokens[0].end_ms == 350
    assert aligned.tokens[1].start_ms == 400
    assert aligned.timing_adjustments[0]["native_token_indices"] == [0, 1]
    # An indivisible native word may not be assigned guessed per-character times.
    with pytest.raises(EditingFailure):
        normalize(
            [{"text": "洗碗", "timestamp": [[100, 700]]}], "洗碗。", parent, prepared
        )
