import pytest
from pydantic import ValidationError

from app.motion_parameter_contracts import clock_category
from app.video_editing_condition_anchors import IncompleteCondition
from app.video_editing_contracts import (
    NativeEventAnchor,
    NativeMediaAnchor,
    NativeTextAnchor,
    SemanticBeat,
    Transcript,
    TranscriptToken,
)
from app.video_editing_quantity_anchors import (
    IncompleteQuantity,
    measured_quantities,
    validate_quantity_slots,
)
from app.video_editing_word_bindings import (
    IncompleteDenial,
    emphasis_text,
    word_bindings,
)
from app.video_editing_yy_openings import validate_yy_opening


def transcript():
    return measured_transcript(["不是", "14.9元，", "每瓶", "1000克。", "洗碗", "洗碗"])


def measured_transcript(words: list[str]) -> Transcript:
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


@pytest.mark.parametrize(
    ("words", "first", "last", "allowed"),
    [
        (["不", "是", "越贵", "越好，"], 2, 3, False),
        (["不", "是", "越贵", "越好，"], 0, 3, True),
        (["不", "是", "越贵", "越好，"], 0, 0, False),
        (["不是", "14.9", "元。"], 2, 2, False),
        (["不是", "1，000", "元。"], 2, 2, False),
        (["不是", "越贵越好", "而是", "看用量"], 3, 3, True),
        (["并非", "洗碗，", "推荐", "刷锅"], 2, 3, True),
        (["是", "不是", "越贵越好？"], 2, 2, True),
    ],
)
def test_original_native_text_keeps_explicit_denial_even_across_beat_boundaries(
    words, first, last, allowed
):
    measured = measured_transcript(words)
    candidate = beat().model_copy(
        update={
            "first_token_id": f"t{first}",
            "last_token_id": f"t{last}",
            "native_text": [
                NativeTextAnchor(
                    path="/content/text",
                    first_token_id=f"t{first}",
                    last_token_id=f"t{last}",
                )
            ],
            "native_events": [],
        }
    )
    if not allowed:
        with pytest.raises(IncompleteDenial):
            word_bindings(candidate, measured, CONTRACT, set())
    else:
        bound = word_bindings(candidate, measured, CONTRACT, set())
        assert bound["text"][0]["text"] == "".join(words[first : last + 1])


@pytest.mark.parametrize(
    ("words", "bad"),
    [
        (["14", "块", "9"], (0, 1)),
        (["14", "块 ", "9"], (0, 1)),
        (["1000", "克"], (0, 0)),
        (["五", "百", "毫", "升"], (1, 3)),
        (["1", "，", "000", "克"], (2, 3)),
        (["14", ".", "9"], (0, 0)),
        (["￥", "14", ".9"], (1, 2)),
        (["两", "大", "瓶"], (0, 0)),
    ],
)
def test_native_text_uses_the_entire_measured_amount(words, bad):
    source = measured_transcript(words)

    def bound(first, last):
        selected = beat().model_copy(
            update={
                "first_token_id": f"t{first}",
                "last_token_id": f"t{last}",
                "native_text": [
                    NativeTextAnchor(
                        path="/content/text",
                        first_token_id=f"t{first}",
                        last_token_id=f"t{last}",
                        punctuation="omit_sentence_punctuation",
                    )
                ],
                "native_events": [],
            }
        )
        return word_bindings(selected, source, CONTRACT, set())

    with pytest.raises(IncompleteQuantity):
        bound(*bad)
    assert bound(0, len(words) - 1)["text"][0]["text"] == "".join(words)


def test_original_number_slots_require_the_same_spoken_occurrence():
    tokens = measured_transcript(["4", "斤，", "4", "斤"]).tokens
    quantities = measured_quantities(tokens)
    for group, partial, full, partial_span, full_span in [
        ("YY6O04", "count", "unit", (0, 0), (1, 1)),
        ("Z-M10", "number", "body", (0, 0), (0, 1)),
        ("W-R07", "label", "numbers/0", (1, 1), (0, 1)),
    ]:
        fields = {f"/content/{partial}": partial_span, f"/content/{full}": full_span}
        validate_quantity_slots(group, fields, quantities)
        with pytest.raises(IncompleteQuantity):
            validate_quantity_slots(
                group,
                {**fields, f"/content/{full}": tuple(i + 2 for i in full_span)},
                quantities,
            )
        with pytest.raises(IncompleteQuantity):
            validate_quantity_slots("BG-S04", fields, quantities)
    independent = measured_quantities(
        measured_transcript(["14", "块", "9", "瓶"]).tokens
    )
    assert [(row.first, row.last) for row in independent] == [(0, 1), (2, 3)]


@pytest.mark.parametrize(
    ("words", "spans", "allowed"),
    [
        (["如", "果", "还能", "下单", "的，", "赶紧", "抢两瓶。"], [(5, 6)], False),
        (
            ["如", "果", "还能", "下单", "的，", "赶紧", "抢两瓶。"],
            [(0, 1), (2, 3), (5, 6)],
            True,
        ),
        (
            ["如", "果", "还能", "下单", "的，", "赶紧", "抢两瓶。"],
            [(0, 2), (5, 6)],
            False,
        ),
        (["只有", "满", "99", "元", "才", "包邮"], [(0, 3), (5, 5)], False),
        (["只有", "满", "99", "元", "才", "包邮"], [(0, 3), (4, 5)], True),
        (["除非", "有券，", "否则", "不能", "退款"], [(0, 2), (4, 4)], False),
        (["仅限", "会员", "使用"], [(1, 2)], False),
        (["如果", "你想少些杂乱，", "可以考虑", "集中整理。"], [(3, 3)], True),
        (["如果", "现在", "就业", "困难。"], [(2, 3)], True),
        (["只有", "天", "才", "知道。"], [(1, 3)], True),
    ],
)
def test_native_condition_can_span_fields_but_must_keep_its_scope(
    words, spans, allowed
):
    source = measured_transcript(words)
    fields = [
        NativeTextAnchor(
            path=f"/content/text{i}",
            first_token_id=f"t{first}",
            last_token_id=f"t{last}",
        )
        for i, (first, last) in enumerate(spans)
    ]
    chosen = beat().model_copy(
        update={
            "first_token_id": fields[0].first_token_id,
            "last_token_id": fields[-1].last_token_id,
            "native_text": fields,
            "native_events": [],
        }
    )
    contract = {**CONTRACT, "text_paths": [field.path for field in fields]}
    if not allowed:
        with pytest.raises(IncompleteCondition):
            word_bindings(chosen, source, contract, set())
    else:
        compiled = word_bindings(chosen, source, contract, set())
        assert [field["text"] for field in compiled["text"]] == [
            "".join(words[first : last + 1]) for first, last in spans
        ]


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


def test_native_anchors_cannot_mix_question_and_smoke_branches():
    contract = {
        **CONTRACT,
        "fields": [
            {"path": "/content/text", "native_branch": "question"},
            {"path": "/events/in", "native_branch": "smoke"},
        ],
    }
    b = beat()
    with pytest.raises(ValueError, match="separate branches"):
        word_bindings(b, transcript(), contract, set())
    b.native_events = []
    assert (
        word_bindings(b, transcript(), contract, set())["text"][0]["text"] == "洗碗洗碗"
    )


def test_number_opening_requires_adjacent_spoken_amount_and_unit():
    words = ["规格", "每瓶", "一千克", "4", "斤", "用好久", "瓶"]
    source = transcript().model_copy(
        update={
            "tokens": [
                TranscriptToken(
                    id=f"t{i}", text=word, start_ms=i * 400, end_ms=(i + 1) * 400
                )
                for i, word in enumerate(words)
            ]
        }
    )
    text_slots = {"topic": 1, "issue": 2, "count": 3, "unit": 4, "subtitle": 5}
    event_slots = {
        "rectangle": 0,
        "topic": 1,
        "issue": 2,
        "circle": 3,
        "response": 3,
        "subtitle": 5,
    }
    anchors = {
        "text": [
            {
                "path": f"/content/{role}",
                "text": words[index],
                "token_ids": [f"t{index}"],
            }
            for role, index in text_slots.items()
        ],
        "events": [
            {
                "path": f"/events/{role}/{offset}",
                "token_id": f"t{index}",
                "value": index * 12 + offset * 12,
                "edge": edge,
            }
            for role, index in event_slots.items()
            for offset, edge in enumerate(("start", "end"))
        ],
    }
    validate_yy_opening("YY6O04", anchors, 84, source)
    unit = next(row for row in anchors["text"] if row["path"] == "/content/unit")
    unit.update(text="瓶", token_ids=["t6"])
    with pytest.raises(ValueError, match="single spoken quantity and its unit"):
        validate_yy_opening("YY6O04", anchors, 84, source)


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
