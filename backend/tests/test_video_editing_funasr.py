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


def test_verified_silent_tail_keeps_analysis_clock_and_clamps_a_measured_end():
    prepared = {
        **PREPARED,
        "clock": {"audio_offset_ms": 0, "silent_tail": {"analysis_audio_end_ms": 3100}},
    }
    raw = fixture()
    raw[0]["timestamp"][-1][1] = 3080
    raw[0]["sentence_info"][-1]["timestamp"][-1][1] = 3080
    transcript = normalize_result(raw, prepared, "local-model", "c" * 64, "1.4.24")
    assert transcript.tokens[-1].end_ms == 3000
    assert (
        transcript.timing_adjustments[0]["reason"]
        == "clip_verified_silent_tail_to_picture_end"
    )
    raw[0]["timestamp"][-1][0] = 3010
    with pytest.raises(EditingFailure, match="EDITING_ASR_TIMING_INVALID"):
        normalize_result(raw, prepared, "local-model", "c" * 64, "1.4.24")


@pytest.mark.parametrize("picture_end", [2930, 3500])
@pytest.mark.parametrize("native_end", [3039, 3069, 3096])
def test_only_final_paraformer_padding_can_cross_the_decoded_audio_end(
    picture_end, native_end
):
    sample_end = 3000
    media_end = min(picture_end, sample_end)
    prepared = {
        **PREPARED,
        "duration_ms": picture_end,
        "clock": {
            **PREPARED["clock"],
            "analysis_audio_end_ms": sample_end,
            **(
                {"silent_tail": {"analysis_audio_end_ms": sample_end}}
                if picture_end < sample_end
                else {}
            ),
        },
    }
    raw = fixture()
    stamps = raw[0]["timestamp"]
    stamps[-1] = [2850, native_end]
    raw[0]["sentence_info"][-1]["timestamp"][-1] = stamps[-1]
    result = normalize_result(raw, prepared, "local-model", "c" * 64, "1.4.24")
    assert result.duration_ms == picture_end
    assert result.tokens[-1].start_ms == 2850
    assert result.tokens[-1].end_ms == result.utterances[-1].end_ms == media_end
    assert result.timing_adjustments == [
        {
            "token_id": "t000008",
            "native_end_ms": native_end,
            "end_ms": media_end,
            "reason": "clip_paraformer_final_padding_to_media_end",
            "analysis_audio_end_ms": sample_end,
        }
    ]
    assert stamps[-1] == [2850, native_end]


@pytest.mark.parametrize(
    ("position", "stamp", "measured_clock", "paraformer"),
    [
        (-2, [2700, 3039], True, True),
        (-1, [2850, 3097], True, True),
        (-1, [3000, 3039], True, True),
        (-1, [2850, 3039], False, True),
        (-1, [2850, 3039], True, False),
    ],
)
def test_unsupported_overshoot_keeps_fail_closed_timing(
    position, stamp, measured_clock, paraformer
):
    prepared = copy.deepcopy(PREPARED)
    if measured_clock:
        prepared["clock"]["analysis_audio_end_ms"] = 3000
    raw = fixture()
    raw[0]["timestamp"][position] = stamp
    raw[0]["sentence_info"][-1]["timestamp"][position] = stamp
    with pytest.raises(EditingFailure, match="EDITING_ASR_TIMING_INVALID"):
        normalize_result(
            raw, prepared, "local-model", "c" * 64, "1.4.24", paraformer=paraformer
        )


@pytest.mark.parametrize("offset", [-20, 0, 15])
def test_paraformer_initial_shift_clips_only_the_first_overlapping_word(offset):
    raw = fixture()
    raw[0]["timestamp"][0] = [-90, 150]
    raw[0]["sentence_info"][0]["timestamp"][0] = raw[0]["timestamp"][0]
    prepared = copy.deepcopy(PREPARED)
    prepared["clock"].update(audio_offset_ms=offset, analysis_audio_end_ms=3000)
    result = normalize_result(raw, prepared, "local-model", "c" * 64, "1.4.24")
    assert result.tokens[0].start_ms == max(0, offset)
    assert result.tokens[0].end_ms == 150 + offset
    assert result.tokens[1].start_ms == raw[0]["timestamp"][1][0] + offset
    assert result.timing_adjustments == [
        {
            "token_id": "t000000",
            "native_start_ms": -90 + offset,
            "start_ms": max(0, offset),
            "reason": "clip_paraformer_initial_shift_to_media_start",
        }
    ]
    assert raw[0]["timestamp"][0] == [-90, 150]


@pytest.mark.parametrize(
    ("position", "stamp", "measured_clock", "paraformer"),
    [
        (0, [-91, 150], True, True),
        (0, [-90, 0], True, True),
        (1, [-90, 300], True, True),
        (0, [-90, 150], False, True),
        (0, [-90, 150], True, False),
    ],
)
def test_invalid_initial_clock_is_rejected(position, stamp, measured_clock, paraformer):
    raw = fixture()
    raw[0]["timestamp"][position] = stamp
    raw[0]["sentence_info"][0]["timestamp"][position] = stamp
    prepared = copy.deepcopy(PREPARED)
    if measured_clock:
        prepared["clock"]["analysis_audio_end_ms"] = 3000
    with pytest.raises(EditingFailure, match="EDITING_ASR_TIMING_INVALID"):
        normalize_result(
            raw, prepared, "local-model", "c" * 64, "1.4.24", paraformer=paraformer
        )


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
