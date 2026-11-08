import pytest
from pydantic import ValidationError

from app.motion_parameter_contracts import clock_category
from app.video_editing_contracts import (
    NativeEventAnchor,
    NativeMediaAnchor,
    SemanticBeat,
    Transcript,
    TranscriptToken,
)
from app.video_editing_word_bindings import emphasis_text, word_bindings


def transcript():
    words = ["不是", "14.9元，", "每瓶", "1000克。", "洗碗", "洗碗"]
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=7000,
        provider="annotated_fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=w, start_ms=100 + i * 1000, end_ms=900 + i * 1000
            )
            for i, w in enumerate(words)
        ],
    )


CONTRACT = {
    "group_id": "G1",
    "native_fps": 30,
    "text_paths": ["/content/text"],
    "event_paths": [{"path": "/events/in", "unit": "frames"}],
    "resource_paths": [{"path": "/media/picture/path", "kind": "image"}],
}


def beat():
    return SemanticBeat(
        id="b",
        first_token_id="t0",
        last_token_id="t5",
        relation="explanation",
        group_id="G1",
        reason="test fixture",
        native_text=[
            {"path": "/content/text", "first_token_id": "t4", "last_token_id": "t5"}
        ],
        native_events=[{"path": "/events/in", "token_id": "t5", "edge": "start"}],
    )


def test_repeated_words_compile_by_occurrence_and_actual_frame_clock():
    t = transcript()
    b = beat()
    result = word_bindings(b, t, CONTRACT, set())
    assert result["text"][0]["text"] == "洗碗洗碗"
    assert (
        result["events"][0]["value"] == 150
    )  # Second occurrence at 5100, native origin at 100.
    assert result["events"][0]["measured_anchor_ms"] == 5100
    assert result["events"][0]["frame_quantization_ms"] == 0
    assert result["runtime_validation"] == "unverified"
    assert (
        emphasis_text(
            "不是14.9元，每瓶1000克，比例2:1，含量25%。", "omit_sentence_punctuation"
        )
        == "不是14.9元每瓶1000克比例2:1含量25%"
    )


def test_model_cannot_use_arbitrary_native_paths_assets_times_or_wrong_occurrences():
    t = transcript()
    original = beat()
    for path in ["/output/path", "/__proto__/polluted", "/media/picture/path"]:
        b = original.model_copy(deep=True)
        b.native_text[0].path = path
        with pytest.raises(ValueError):
            word_bindings(b, t, CONTRACT, set())
    b = original.model_copy(deep=True)
    b.first_token_id = "t4"
    b.native_text[0].first_token_id = "t0"
    with pytest.raises(ValueError):
        word_bindings(b, t, CONTRACT, set())
    b = original.model_copy(deep=True)
    b.native_media = [
        NativeMediaAnchor(path="/media/picture/path", asset_id="invented")
    ]
    with pytest.raises(ValueError):
        word_bindings(b, t, CONTRACT, set())
    with pytest.raises(ValidationError):
        NativeEventAnchor(path="/events/in", token_id="t5", edge="start", seconds=1.2)
    damaged = t.model_dump()
    damaged["tokens"][5]["id"] = "t4"
    with pytest.raises(ValidationError):
        Transcript.model_validate(damaged)


def test_native_offsets_lengths_and_rates_are_not_absolute_word_events():
    assert clock_category("scene", ["events", "shift_frames"]) == "native_clock_offset"
    assert clock_category("browser", ["items", "enter"]) == "native_clock_length"
    assert (
        clock_category("unified", ["timing", "events", "hand_speeds"]) == "native_rate"
    )
    for key in [
        "char_stagger_frames",
        "cell_step",
        "settle_duration",
        "type_interval_frames",
    ]:
        assert clock_category("subtitle", ["events", key]) == "native_clock_length"
    # Despite its name, BG-S03 offset_frame is an absolute onset of repositioning.
    assert clock_category("subtitle", ["events", "offset_frame"]) is None
