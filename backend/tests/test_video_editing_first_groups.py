from app import video_editing_first_groups as first_groups
from app.video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from app.video_editing_first_groups import (
    ShotChoice,
    _Candidate,
    _dense_words,
    _find_dense_target,
    _fit_examples,
    _pair,
    _select_dense,
    _shorten_phrase,
)
from app.video_editing_quantity_anchors import (
    measured_quantities,
    validate_quantity_slots,
)
from app.video_editing_yy_openings import yy08_spoken_question


def _transcript(words: list[str]) -> Transcript:
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=len(words) * 1000,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(
                id=str(i), text=word, start_ms=i * 1000, end_ms=i * 1000 + 500
            )
            for i, word in enumerate(words)
        ],
    )


def _candidate(group: str, begin: int, end: int, *assets: str) -> _Candidate:
    beat = SemanticBeat(
        id=f"{group}-{begin}",
        group_id=group,
        first_token_id=str(begin),
        last_token_id=str(end),
        relation="explanation",
        reason="同一段实录的候选",
        asset_ids=list(assets),
    )
    return _Candidate(begin, end, beat, None)


def test_dense_selection_keeps_opening_variety_and_repeats_at_separate_words():
    transcript = _transcript(["词"] * 16)
    long_opening = _candidate("Z-M02", 1, 7)
    first = _candidate("BG-S04", 1, 2)
    second = _candidate("Z-M02", 5, 6)
    repeat = _candidate("BG-S04", 9, 10)
    close = _candidate("Z-M04", 12, 15)
    assert _select_dense([long_opening, close, second, first, repeat], transcript) == [
        first,
        second,
        repeat,
        close,
    ]
    target = _find_dense_target(
        [long_opening, close, second, first, repeat],
        transcript,
        3,
        quick_opening=True,
    )
    assert target is not None
    assert target[:2] == [first, second]
    assert {item.beat.group_id for item in target} == {"BG-S04", "Z-M02", "Z-M04"}


def test_scoped_pool_uses_relevant_project_image_after_preserving_five_types():
    transcript = _transcript(["词"] * 20)
    first = _candidate("AH-S09", 0, 1)
    split = _candidate("CX-G02", 3, 8, "material-a")
    short = _candidate("BG-S04", 3, 4)
    extra = _candidate("SG-S03", 6, 7)
    end = [
        _candidate("YYP01", 9, 10),
        _candidate("AHG-S02", 12, 13),
        _candidate("AH-S05", 15, 16),
    ]
    candidates = [first, split, short, extra, *end]
    assert _select_dense(candidates, transcript, selected_images={"material-a"}) == [
        first,
        split,
        *end,
    ]
    assert split not in _select_dense(
        [first, split, short, extra, *end[1:]],
        transcript,
        selected_images={"material-a"},
    )


def test_shorter_native_text_keeps_the_spoken_quantity_and_condition():
    action = _transcript(["赶紧", "去", "抢", "两", "瓶"])
    assert _shorten_phrase(action, (0, 4), (1, 4)) == (1, 4)
    condition = _transcript(["如果", "还", "能", "下单"])
    assert _shorten_phrase(condition, (0, 3), (1, 2)) == (0, 3)


def test_yy08_inactive_title_can_reuse_a_complete_spoken_phrase():
    transcript = _transcript(["14", "块", "9", "合", "适", "吗？"])
    shot = ShotChoice(
        group="YYO08", span=(0, 5), words=[(0, 2), (3, 5)], why="价格与规格"
    )
    binding = _dense_words(shot, transcript, "source")

    assert binding.relation == "question"
    assert binding.text["/content/topic"] == (0, 2)
    assert binding.text["/content/question"] == (3, 5)
    assert binding.text["/content/title"] == (3, 5)
    assert binding.events["/events/title_in"] == (0, "start")
    assert binding.events["/events/question_in"] == (3, "start")
    validate_quantity_slots(
        "YYO08", binding.text, measured_quantities(transcript.tokens)
    )


def test_yy08_preflight_offers_questions_at_the_original_push_in():
    transcript = _transcript(["上新，", "哪张图？", "接下来"])
    assert _fit_examples(transcript, {"YYO08"}, None)["YYO08"] == [(0, 0, 1, 1, 2)]

    statement = _transcript(["到手，", "两大瓶，", "接下来"])
    assert "YYO08" not in _fit_examples(statement, {"YYO08"}, None)


def test_yy08_question_evidence_keeps_ratios_and_stays_in_one_clause():
    transcript = _transcript(["3:2吗？！", "可以吗", "两瓶，", "合适？"])
    assert yy08_spoken_question(transcript.tokens, 0, 0)
    assert yy08_spoken_question(transcript.tokens, 1, 1)
    assert not yy08_spoken_question(transcript.tokens, 2, 3)


def test_line_entrance_can_settle_at_a_measured_edge_during_a_spoken_pause():
    transcript = _transcript(["核", "对", "成", "片", "后"])
    shot = ShotChoice(
        group="JJ-S03", span=(0, 4), words=[(0, 1), (2, 3)], why="核对成片"
    )
    anchors = _pair(shot, transcript, None, align_line_entrance=True)
    assert anchors.events["/events/line/0"] == (0, "start")
    assert anchors.events["/events/line/1"] == (0, "end")
    assert anchors.events["/events/emphasis/0"] == (2, "start")


def test_compact_fit_examples_use_only_selectable_slots(monkeypatch):
    transcript = _transcript(["词", "项"])
    template = {
        "slots": [{"group_id": group} for group in ("BG-S04", "BG-S06", "SG-S03")]
    }
    payload = {
        "full_library": [
            {"id": group} for group in ("BG-S04", "BG-S06", "SG-S03", "HY-A2")
        ],
        "template_runtime": {"unavailable_groups": {"BG-S06": ["font"]}},
        "project_library_choices": {
            "notes": [
                {"target_kind": "group", "target_id": "SG-S03", "choice": "avoid"}
            ]
        },
        "available_project_materials": [],
    }
    monkeypatch.setattr(
        first_groups, "_fit_examples", lambda _, groups, _q: sorted(groups)
    )
    compact = first_groups.compact_payload(
        payload, transcript, template, preflight_policy=True
    )
    assert compact["fit_examples"] == ["BG-S04"]
    assert compact["word_clock"] == [[0, "词", 0, 500], [1, "项", 1000, 1500]]
