"""AH-S03 input A keeps the original frame and font roles separate from B."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.motion_browser_originals import original_startup_assets
from app.motion_library import atomic_json
from app.video_editing_contracts import (
    SemanticBeat,
    SemanticPlan,
    Transcript,
    TranscriptToken,
)
from app.video_editing_overlay_templates import (
    QUESTION_CARD_TEMPLATE_ID,
    overlay_template,
    validate_template_plan,
)
from app.video_editing_question_card import (
    QUESTION_CARD_A_FONTS,
    QUESTION_CARD_B_FONTS,
    QUESTION_CARD_EVENTS,
    QUESTION_CARD_LABELS,
    automatic_question_card_gloss,
    question_card_entry_frame,
    question_card_gloss,
)
from app.video_editing_word_bindings import word_bindings


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


@pytest.mark.parametrize("font_ids", [QUESTION_CARD_A_FONTS, QUESTION_CARD_B_FONTS])
def test_native_entry_clock_uses_first_visible_frame(font_ids):
    roles = (
        ("english", "question")
        if len(font_ids) == 2
        else ("chinese", "english", "question")
    )
    shot = {
        "group_id": "AH-S03",
        "layer": "subtitle",
        "start_seconds": 4.870,
        "config": {
            "fonts": {
                role: {"path": "input://" + rid}
                for role, rid in zip(roles, font_ids, strict=True)
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
            "entry/legacy/assets/img/person.png": "input://media-person",
            "entry/legacy/assets/img/g06-bg.png": "input://media-background",
        },
    )
    atomic_json(tmp_path / "catalog/external-resources.json", {"resources": []})
    result = original_startup_assets(
        tmp_path, {"id": "CX-G08", "browser_directory": "entry"}
    )
    assert [(row["bundled_count"], row["expected_count"]) for row in result] == [
        (0, 3),
        (1, 66),
        (0, 1),
        (0, 1),
        (0, 1),
        (0, 1),
    ]
    assert result[2]["indexed_external_ids"] == ["media-original"]
    assert result[1]["verified_bundled_count"] == 0
    assert all(row["usage"] == "shared_startup" for row in result[:-2])
    assert result[-2]["usage"] == "without_presenter"
    assert result[-2]["indexed_external_ids"] == ["media-person"]
    assert result[-1]["usage"] == "shared_startup"
    shared = original_startup_assets(
        tmp_path, {"id": "CX-G09", "browser_directory": "entry"}
    )
    assert shared[-2]["usage"] == "shared_startup"
    list_group = original_startup_assets(
        tmp_path, {"id": "CX-G06", "browser_directory": "entry"}
    )
    assert list_group[-2]["usage"] == "without_presenter"
    assert list_group[-1]["usage"] == "unless_native_solid_background"
    assert list_group[-1]["indexed_external_ids"] == ["media-background"]


def test_automatic_question_gloss_keeps_measured_roles_and_native_tail():
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=1500,
        provider="fixture",
        model="word-clocks",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=str(i), text=text, start_ms=i * 200, end_ms=(i + 1) * 200
            )
            for i, text in enumerate(("你", "们", "谁", "之", "前", "买", "过"))
        ],
    )
    beat = SemanticBeat.model_validate(
        {
            "id": "question",
            "group_id": "AH-S03",
            "reason": "实录追问",
            "relation": "question",
            "first_token_id": "0",
            "last_token_id": "6",
            "question_gloss": "WHO AMONG YOU",
            "native_text": [
                {"path": path, "first_token_id": first, "last_token_id": last}
                for path, (first, last) in zip(
                    QUESTION_CARD_LABELS, (("0", "1"), ("2", "2")), strict=True
                )
            ],
            "native_events": [
                {"path": path, "token_id": token, "edge": edge}
                for path, (token, edge) in zip(
                    QUESTION_CARD_EVENTS,
                    (
                        ("0", "start"),
                        ("1", "start"),
                        ("2", "start"),
                        ("4", "start"),
                        ("4", "end"),
                    ),
                    strict=True,
                )
            ],
        }
    )
    contract = {
        "group_id": "AH-S03",
        "native_fps": 30,
        "text_paths": list(QUESTION_CARD_LABELS),
        "event_paths": [
            {"path": path, "unit": "frames"} for path in QUESTION_CARD_EVENTS
        ],
    }
    anchors = word_bindings(beat, transcript, contract, set())
    assert automatic_question_card_gloss(beat, anchors, transcript) == {
        "source_text": "你们谁",
        "display_text": "WHO AMONG YOU",
    }
    plan = SemanticPlan(
        audience_question="用途",
        argument_outline=["追问"],
        style_reason="用途",
        beats=[beat],
    )
    template = overlay_template(QUESTION_CARD_TEMPLATE_ID)
    validate_template_plan(plan, template, complete=False)
    with pytest.raises(ValueError, match="selected AH-S03 A slot"):
        validate_template_plan(
            plan, overlay_template("question-story-v1"), complete=False
        )
    without_gloss = beat.model_copy(update={"question_gloss": None})
    assert "question_gloss" not in without_gloss.model_dump(mode="json")
    with pytest.raises(ValueError, match="selected AH-S03 A slot"):
        validate_template_plan(
            plan.model_copy(update={"beats": [without_gloss]}), template, complete=False
        )

    bad = deepcopy(anchors)
    bad["events"][2]["token_id"] = "1"
    with pytest.raises(ValueError, match="ordered spoken entrances"):
        automatic_question_card_gloss(beat, bad, transcript)
    bad = deepcopy(anchors)
    bad["events"][3]["value"] = bad["events"][2]["value"] + 8
    with pytest.raises(ValueError, match="settling time"):
        automatic_question_card_gloss(beat, bad, transcript)
    bad = deepcopy(anchors)
    bad["events"][4]["value"] = 42
    with pytest.raises(ValueError, match="settling time"):
        automatic_question_card_gloss(beat, bad, transcript)
