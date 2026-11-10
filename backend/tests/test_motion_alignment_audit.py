import pytest

from app.video_editing_contracts import Transcript, TranscriptToken, TranscriptUtterance
from scripts.audit_motion_alignment import Mark, Reference, score


def transcript():
    return Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=5000,
        provider="funasr",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(id="t0", text="洗", start_ms=112, end_ms=212),
            TranscriptToken(id="t1", text="碗。", start_ms=212, end_ms=412),
            TranscriptToken(id="t2", text="洗", start_ms=1112, end_ms=1212),
            TranscriptToken(id="t3", text="碗，", start_ms=1212, end_ms=1412),
            TranscriptToken(id="t4", text="倒", start_ms=1412, end_ms=1612),
            TranscriptToken(id="t5", text="14.", start_ms=1612, end_ms=1812),
            TranscriptToken(id="t6", text="9。", start_ms=1812, end_ms=1912),
        ],
        utterances=[
            TranscriptUtterance(
                id="u0", text="洗碗。", token_ids=["t0", "t1"], start_ms=112, end_ms=412
            ),
            TranscriptUtterance(
                id="u1",
                text="洗碗，倒14.9。",
                token_ids=["t2", "t3", "t4", "t5", "t6"],
                start_ms=1112,
                end_ms=1912,
            ),
        ],
    )


def word(text, *, at=100, occurrence=1, occurrences=1):
    return Mark(
        kind="word",
        text=text,
        occurrence=occurrence,
        occurrences=occurrences,
        start_ms=at,
    )


def utterance(text, *, start, end, occurrence=1, occurrences=1):
    return Mark(
        kind="utterance",
        text=text,
        occurrence=occurrence,
        occurrences=occurrences,
        start_ms=start,
        end_ms=end,
    )


def reference(*marks):
    return Reference(
        schema_version="tengli.motion-timing-reference/1",
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        timebase="analysis_wav_ms",
        origin="diagnostic",
        marks=list(marks),
    )


def test_audit_uses_exact_occurrence_and_measured_wav_clock():
    result = score(
        transcript(),
        reference(
            word("洗碗", at=950, occurrence=2, occurrences=2),
            word("14.9", at=1750),
            utterance("洗碗，倒14.9", start=1100, end=2200),
        ),
        12,
        5012,
    )
    assert result["status"] == "sample_within_tolerance"
    assert result["origin"] == "diagnostic"
    repeated, number, sentence = result["marks"]
    assert repeated["first_token_id"] == "t2"
    assert repeated["measured_start_wav_ms"] == 1100
    assert repeated["start_error_ms"] == 150
    assert number["start_error_ms"] == -150
    assert sentence["utterance_id"] == "u1"
    assert sentence["end_error_ms"] == -300


def test_audit_keeps_unmatched_labels_in_the_denominator():
    result = score(
        transcript(),
        reference(
            word("洗碗", occurrences=1),
            word("149"),
            word("4.9"),
            word("洗碗", at=949, occurrence=2, occurrences=2),
            utterance("洗碗", start=1100, end=1400, occurrence=2, occurrences=2),
            utterance("洗碗，倒14.9", start=1100, end=2201),
        ),
        12,
        5012,
    )
    assert result["status"] == "sample_failed"
    assert [row["result"] for row in result["marks"]] == [
        "occurrence_count_mismatch",
        "occurrence_count_mismatch",
        "inside_measured_token",
        "out_of_tolerance",
        "utterance_boundary_mismatch",
        "out_of_tolerance",
    ]
    assert result["summary"]["word"] == {
        "labels": 4,
        "measured": 1,
        "within_tolerance": 0,
        "max_absolute_error_ms": 151,
    }


def test_audit_rejects_changed_identity_duplicate_and_out_of_range_marks():
    tx = transcript()
    valid = word("洗碗", occurrences=2)
    only_words = score(tx, reference(valid), 12, 5012)
    assert only_words["status"] == "sample_incomplete"
    assert only_words["summary"]["utterance"]["max_absolute_error_ms"] is None
    wrong = reference(valid).model_copy(update={"audio_sha256": "c" * 64})
    with pytest.raises(ValueError, match="same recording"):
        score(tx, wrong, 12, 5012)
    with pytest.raises(ValueError, match="Duplicate"):
        score(tx, reference(valid, valid), 12, 5012)
    with pytest.raises(ValueError, match="beyond the WAV"):
        score(tx, reference(word("洗碗", at=5000, occurrences=2)), 12, 5012)
