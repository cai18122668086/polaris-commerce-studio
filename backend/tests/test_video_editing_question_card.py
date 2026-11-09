"""AH-S03 input A keeps the original frame and font roles separate from B."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.motion_library import atomic_json
from app.video_editing_catalog import original_startup_assets
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_question_card import (
    QUESTION_CARD_A_FONTS,
    question_card_entry_frame,
    question_card_gloss,
)


def test_gloss_requires_adjacent_current_words():
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=800,
        provider="fixture",
        model="word-clocks",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=str(i), text=text, start_ms=200 * i, end_ms=200 * (i + 1)
            )
            for i, text in enumerate(("你", "们", "谁"))
        ],
    )
    native = {
        "text": [
            {"path": "/content/left", "text": "你们", "token_ids": ["0", "1"]},
            {"path": "/content/right", "text": "谁", "token_ids": ["2"]},
        ]
    }
    gloss = {"source_text": "你们谁", "display_text": "WHO AMONG YOU"}
    assert question_card_gloss(native, gloss, transcript)["source_token_ids"] == [
        "0",
        "1",
        "2",
    ]
    with pytest.raises(ValueError, match="both spoken labels"):
        question_card_gloss(native, {**gloss, "source_text": "谁"}, transcript)
    missing_word = deepcopy(native)
    missing_word["text"][0] = {
        "path": "/content/left",
        "text": "你",
        "token_ids": ["0"],
    }
    with pytest.raises(ValueError, match="both spoken labels"):
        question_card_gloss(missing_word, {**gloss, "source_text": "你谁"}, transcript)


def test_native_entry_clock_uses_first_visible_frame():
    english, question = QUESTION_CARD_A_FONTS
    shot = {
        "group_id": "AH-S03",
        "layer": "subtitle",
        "start_seconds": 4.870,
        "config": {
            "fonts": {
                "english": {"path": "input://" + english},
                "question": {"path": "input://" + question},
            },
            "events": {"question_frame": 10, "exit_frame": 22},
        },
    }
    assert question_card_entry_frame(shot, 30, "/events/question_frame") == 157
    with pytest.raises(ValueError, match="30 fps"):
        question_card_entry_frame(shot, 24, "/events/question_frame")
    with pytest.raises(ValueError, match="30 fps"):
        question_card_entry_frame(shot, 30, "/events/exit_frame")


def test_shared_browser_startup_assets_count_archived_files_and_external_references(
    tmp_path: Path,
):
    (tmp_path / "catalog").mkdir()
    atomic_json(
        tmp_path / "integrity.json", {"files": {"entry/assets/g09-bg/000.jpg": "a"}}
    )
    atomic_json(
        tmp_path / "catalog/native-relative-assets.json",
        {
            "entry/assets/G10-background-clean.jpg": "input://media-original",
        },
    )
    result = original_startup_assets(
        tmp_path, {"id": "CX-G08", "browser_directory": "entry"}
    )
    assert [(row["bundled_count"], row["expected_count"]) for row in result] == [
        (0, 3),
        (1, 66),
        (0, 1),
        (0, 1),
    ]
    assert result[2]["indexed_external_ids"] == ["media-original"]
    assert original_startup_assets(tmp_path, {"id": "CX-G04"}) == []
