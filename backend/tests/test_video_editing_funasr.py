import copy

import pytest

from app.video_editing_funasr import normalize_result
from app.video_editing_pipeline import EditingFailure, caption_rows


def fixture():
    words = ["不", "是", "贵", "就", "好", "A", "类", "1000", "克"]
    times = [[100 + i * 200, 250 + i * 200] for i in range(len(words))]
    return [
        {
            "raw_text": " ".join(words),
            "text": "不是贵就好，A类1000克。",
            "timestamp": times,
            "sentence_info": [
                {"raw_text": " ".join(words[:5]), "timestamp": times[:5]},
                {"raw_text": " ".join(words[5:]), "timestamp": times[5:]},
            ],
        }
    ]


PREPARED = {
    "audio_sha256": "a" * 64,
    "source_sha256": "b" * 64,
    "duration_ms": 3000,
    "clock": {"audio_offset_ms": 0},
}


def test_actual_funasr_clocks_survive_punctuation_and_mixed_units():
    raw = fixture()
    result = normalize_result(raw, PREPARED, "local-model", "c" * 64, "1.4.24")
    assert [[t.start_ms, t.end_ms] for t in result.tokens] == raw[0]["timestamp"]
    assert "".join(t.text for t in result.tokens) == raw[0]["text"]
    assert result.tokens[4].text == "好，"
    assert result.tokens[7].text == "1000"
    assert result.utterances[1].token_ids == [f"t{i:06}" for i in range(5, 9)]
    assert result.timing_review == "unreviewed"
    assert result.reference_matches is None
    assert result.raw_result_sha256 is not None
    assert caption_rows(result)[-1]["end_seconds"] == 1.85


def test_small_model_tail_quantization_is_clipped_and_recorded():
    raw = fixture()
    raw[0]["timestamp"][-1][1] = 3024
    raw[0]["sentence_info"][-1]["timestamp"][-1][1] = 3024
    result = normalize_result(raw, PREPARED, "local-model", "c" * 64, "1.4.24")
    assert result.tokens[-1].end_ms == PREPARED["duration_ms"]
    assert result.timing_adjustments == [
        {
            "token_id": "t000008",
            "native_end_ms": 3024,
            "end_ms": 3000,
            "reason": "clip_model_quantization_to_actual_audio_end",
        }
    ]
    assert raw[0]["timestamp"][-1][1] == 3024


@pytest.mark.parametrize(
    "variant", ["count", "surface", "sentence", "zero", "overlap", "outside"]
)
def test_missing_or_inconsistent_funasr_anchors_are_never_estimated(variant):
    raw = copy.deepcopy(fixture())
    row = raw[0]
    if variant == "count":
        row["timestamp"] = row["timestamp"][:-1]
    elif variant == "surface":
        row["text"] = "是贵就好，A类1000克。"  # Dropped negation must fail.
    elif variant == "sentence":
        row["sentence_info"] = row["sentence_info"][:-1]
    elif variant == "zero":
        row["timestamp"][0] = [100, 100]
    elif variant == "overlap":
        row["timestamp"][1] = [200, 450]
    else:
        row["timestamp"][-1] = [3000, 3200]
    with pytest.raises(EditingFailure):
        normalize_result(raw, PREPARED, "local-model", "c" * 64, "1.4.24")
