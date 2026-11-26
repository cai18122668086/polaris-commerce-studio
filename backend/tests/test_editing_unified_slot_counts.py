"""knowledge-talk: Z-M03 got 1 of its 3 label slots (planning 2047ecb8).

The prompt now states each group's fixed slot counts, and the planner binds
list slots the beat's own relation_items declare, downgrades an incomplete
signature scene only when enough complete signature scenes remain, and
otherwise fails at planning naming the empty slots.
"""

import copy
import json
from pathlib import Path

import pytest

from app import video_editing_overlay_recipes as recipes
from app.errors import ApiError
from app.video_editing_contracts import SemanticPlan
from app.video_editing_planning_quality import (
    NATIVE_SLOT_COUNTS_POLICY,
    NATIVE_SLOT_COUNTS_PROMPT,
)
from app.video_editing_unified_repair import repair_unified_beats
from app.video_editing_unified_scenes import missing_native_slots, native_slot_counts

ZM03_TEXT = [
    "/content/title",
    "/content/labels/0",
    "/content/labels/1",
    "/content/labels/2",
    "/content/summary",
]
ZM03_EVENTS = [
    {"path": f"/timing/events/{name}", "unit": "seconds"}
    for name in ("title", "item0", "item1", "item2", "summary")
]


def saved():
    path = Path(__file__).parent / "fixtures/knowledge_talk_unbound_scene_assets.json"
    return json.loads(path.read_text("utf-8"))["plan"]


def semantic(raw):
    return SemanticPlan.model_validate(
        {k: v for k, v in raw.items() if k != "tutorial_steps"}
    )


def fake_entry(package, group, beat, transcript, asset_cards, **_):
    labels = [t for t in beat.native_text if "/labels/" in t.path]
    events = {e.path for e in beat.native_events}
    if beat.group_id == "Z-M03" and (
        len(labels) != 3
        or not {f"/timing/events/item{i}" for i in range(3)} <= events
        or len(beat.relation_items) < 3
    ):
        raise ApiError(422, "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED", "x")
    return None, {}


@pytest.fixture
def package(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "_unified_entry", fake_entry)
    (tmp_path / "catalog").mkdir()
    groups = [{"id": g} for g in ("Z-M01", "Z-M02", "Z-M03", "Z-M13", "Z-M14")]
    (tmp_path / "catalog/groups.json").write_text(json.dumps({"groups": groups}))
    return tmp_path


def test_slot_counts_state_the_fixed_label_count_and_capacities():
    counts = native_slot_counts("Z-M03", ZM03_TEXT, ZM03_EVENTS)
    assert counts == {
        "text_paths": 5,
        "event_paths": 5,
        "lists": {"/content/labels": 3},
        "relation": "parallel",
        "relation_items": 3,
        "max_chars": {
            "/content/title": 12,
            "/content/labels/0": 5,
            "/content/labels/1": 5,
            "/content/labels/2": 5,
            "/content/summary": 7,
        },
    }
    assert native_slot_counts("Z-M00", ["/content/captions/0/text"], []) is None
    assert (
        "Z-M03" in NATIVE_SLOT_COUNTS_PROMPT and "per_page" in NATIVE_SLOT_COUNTS_PROMPT
    )
    assert NATIVE_SLOT_COUNTS_POLICY.endswith("/1")


def test_saved_response_reports_the_empty_label_slots():
    beat = semantic(saved()).beats[0]
    assert beat.group_id == "Z-M03"
    gaps = missing_native_slots(
        beat, {"text_paths": ZM03_TEXT, "event_paths": ZM03_EVENTS}
    )
    assert gaps == [
        "/content/labels/1",
        "/content/labels/2",
        "/timing/events/item1",
        "/timing/events/item2",
        "relation_items 2/3",
    ]


def test_saved_response_still_fails_at_planning_without_another_signature(package):
    raw = saved()
    with pytest.raises(ApiError) as caught:
        repair_unified_beats(
            raw, semantic(raw), package, None, [], {"Z-M03", "Z-M13"}, 1
        )
    assert caught.value.code == "EDITING_TEMPLATE_UNIFIED_INPUTS_REQUIRED"


def test_labels_declared_by_relation_items_are_bound(package):
    raw = saved()
    beat = raw["beats"][0]
    ids = [f"fb45384b60578-t{i:06d}" for i in range(19)]
    beat["relation"] = "parallel"
    beat["relation_items"] = [
        {
            "id": f"ri-{n}",
            "first_token_id": ids[a],
            "last_token_id": ids[b],
            "asset_ids": [],
            "native_text_paths": [f"/content/labels/{n}"],
            "native_media_paths": [],
        }
        for n, (a, b) in enumerate(((2, 3), (10, 12), (16, 18)))
    ]
    before = copy.deepcopy(raw)
    changed, repairs = repair_unified_beats(
        raw, semantic(raw), package, None, [], {"Z-M03", "Z-M13"}, 1
    )
    assert raw == before
    bound = next(r for r in repairs if r["kind"] == "declared_relation_slots_bound")
    assert bound["paths"] == [
        "/content/labels/1",
        "/timing/events/item1",
        "/content/labels/2",
        "/timing/events/item2",
    ]
    fixed = changed["beats"][0]
    assert fixed["group_id"] == "Z-M03"
    label1 = next(t for t in fixed["native_text"] if t["path"] == "/content/labels/1")
    assert (label1["first_token_id"], label1["last_token_id"]) == (ids[10], ids[12])
    item2 = next(
        e for e in fixed["native_events"] if e["path"] == "/timing/events/item2"
    )
    assert item2 == {
        "path": "/timing/events/item2",
        "token_id": ids[16],
        "edge": "start",
    }
    semantic(changed)


def test_incomplete_signature_is_plain_when_another_signature_scene_remains(package):
    raw = saved()
    raw["beats"][2]["group_id"] = "Z-M13"  # A complete signature scene elsewhere.
    changed, repairs = repair_unified_beats(
        raw, semantic(raw), package, None, [], {"Z-M03", "Z-M13"}, 1
    )
    assert {
        "kind": "incomplete_scene_to_plain_presenter",
        "beat_id": "beat-01",
        "group_id": "Z-M03",
        "reason": "native_slots_incomplete",
    } in repairs
    assert changed["beats"][0]["group_id"] == "Z-M00"
    assert changed["beats"][2]["group_id"] == "Z-M13"
    with pytest.raises(ApiError):  # Two signature scenes required: still strict.
        repair_unified_beats(
            raw, semantic(raw), package, None, [], {"Z-M03", "Z-M13"}, 2
        )
