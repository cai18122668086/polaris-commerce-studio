import pytest

from app.video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from app.video_editing_native_content import (
    chapter_ordinal,
    number_glyphs,
    translation_labels,
)


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


def test_translation_labels_require_matching_spoken_occurrences():
    native = {
        "group_id": "W-R02",
        "text": [
            {"path": "/content/before", "text": "每瓶", "token_ids": ["t0", "t1"]},
            {"path": "/content/after", "text": "到手", "token_ids": ["t3", "t4"]},
            {"path": "/content/caption_before", "token_ids": ["t0", "t1", "t2"]},
            {"path": "/content/caption_after", "token_ids": ["t3", "t4", "t5"]},
        ],
    }
    labels = {
        "before": {"source_text": "每瓶", "display_text": "PER BOTTLE"},
        "after": {"source_text": "到手", "display_text": "TOTAL"},
    }
    result = translation_labels(native, labels)
    assert [r["display_text"] for r in result] == ["PER BOTTLE", "TOTAL"]
    assert result[0]["source_token_ids"] == ["t0", "t1"]
    assert result[1]["semantic_review"] == "unreviewed"
    assert result[1]["origin"] == "trusted_recipe"
    labels["after"]["display_text"] = "<script>"
    with pytest.raises(ValueError, match="short uppercase English"):
        translation_labels(native, labels)
    labels["after"]["display_text"] = "TOTAL"
    native["text"][3]["token_ids"] = ["t6", "t7"]
    with pytest.raises(ValueError, match="its own spoken label and caption"):
        translation_labels(native, labels)
