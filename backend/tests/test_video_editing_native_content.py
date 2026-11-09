import pytest

from app.video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from app.video_editing_native_content import chapter_ordinal, number_glyphs


def test_chapter_ordinal_is_derived_from_ordered_source_starts():
    transcript = Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=3000,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"t{i}", text="段", start_ms=i * 500, end_ms=(i + 1) * 500
            )
            for i in range(6)
        ],
        utterances=[],
    )
    beat = SemanticBeat(
        id="chapter",
        group_id="Z-M15",
        first_token_id="t2",
        last_token_id="t3",
        relation="explanation",
        reason="章次对照",
    )
    proof = chapter_ordinal(beat, transcript, ["t0", "t2", "t4"])
    assert proof["display_text"] == "Second" and proof["chapter_number"] == 2
    with pytest.raises(ValueError, match="follow source order"):
        chapter_ordinal(beat, transcript, ["t0", "t4", "t2"])
    with pytest.raises(ValueError, match="saved outline anchor"):
        chapter_ordinal(beat, transcript, ["t0", "t1", "t4"])
    with pytest.raises(ValueError, match="saved outline interval"):
        chapter_ordinal(beat, transcript, ["t0", "t2", "t3"])


def test_original_number_glyphs_preserve_each_spoken_unit_and_its_reveal():
    native = {
        "text": [
            {"path": "/content/numbers/0", "text": "两斤", "token_ids": ["t1", "t2"]},
            {"path": "/content/numbers/1", "text": "4斤", "token_ids": ["t4", "t5"]},
            {"path": "/content/label", "text": "斤", "token_ids": ["t2"]},
            {
                "path": "/content/captions/0",
                "text": "每瓶两斤",
                "token_ids": ["t0", "t1", "t2"],
            },
            {
                "path": "/content/captions/1",
                "text": "到手4斤",
                "token_ids": ["t3", "t4", "t5"],
            },
        ],
        "events": [
            {"path": "/timing/events/black_in", "token_id": "t1", "edge": "start"},
            {"path": "/timing/events/second_number", "token_id": "t4", "edge": "start"},
        ],
    }
    proof = number_glyphs(native)
    assert [row["display_text"] for row in proof] == ["2", "4"]
    assert proof[0]["text"] == "两斤" and proof[1]["unit"] == "斤"
    native["text"][1]["text"] = "4克"
    with pytest.raises(ValueError, match="same spoken unit"):
        number_glyphs(native)
    native["text"][1]["text"] = "4斤"
    native["events"][1]["token_id"] = "t3"
    with pytest.raises(ValueError, match="spoken amount start"):
        number_glyphs(native)
    native["events"][1]["token_id"] = "t4"
    native["text"][4]["token_ids"] = ["t4", "t6", "t5"]
    with pytest.raises(ValueError, match="within its own caption"):
        number_glyphs(native)
