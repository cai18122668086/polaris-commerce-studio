from app.video_editing_contracts import SemanticBeat
from app.video_editing_planner import BEAT_RELATIONS, normalize_beat_relations


def test_allowed_set_matches_the_contract():
    allowed = set(SemanticBeat.model_fields["relation"].annotation.__args__)
    assert allowed == set(BEAT_RELATIONS)


def test_invented_relations_are_mapped_and_recorded():
    raw = {
        "beats": [
            {"id": "b1", "relation": "chapter"},
            {"id": "b2", "relation": "cause"},
            {"id": "b3", "relation": "Highlight"},
        ]
    }
    fixed, repairs = normalize_beat_relations(raw)
    assert [b["relation"] for b in fixed["beats"]] == [
        "sequence",
        "cause",
        "explanation",
    ]
    assert [r["beat"] for r in repairs] == [0, 2]
    assert raw["beats"][0]["relation"] == "chapter"  # input untouched


def test_valid_plans_are_returned_unchanged():
    raw = {"beats": [{"id": "b1", "relation": "summary"}]}
    fixed, repairs = normalize_beat_relations(raw)
    assert fixed is raw and repairs == []
