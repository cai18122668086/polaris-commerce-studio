"""bihuo-info-card/1: the opening info card reads in spoken order."""

from __future__ import annotations

from copy import deepcopy

from app.bihuo_suite import info_card


def payload(
    title="这款白色",
    subtitle="头戴耳机，",
    spoken="这款白色头戴耳机，我在办公桌上用了一个月。",
):
    scene = dict(
        at=0, nav=title, nav_support=subtitle, label=title, gray=subtitle, blue=title
    )
    return {
        "template_id": "bihuo-03-v1",
        "config": {
            "engine": "app-window",
            "header_title": title,
            "header_support": subtitle,
            "chapters": [scene],
            "resolved_plan": {"tokens": [{"text": ch} for ch in spoken]},
        },
    }


def test_split_phrase_reads_in_spoken_order_without_repeating_the_label():
    out = info_card.apply(payload())
    cfg = out["config"]
    scene = cfg["chapters"][0]
    assert (scene["gray"], scene["blue"]) == ("这款白色", "头戴耳机")
    assert scene["label"] == ""
    # Header and navigation keep title before subtitle.
    assert (cfg["header_title"], cfg["header_support"]) == ("这款白色", "头戴耳机，")
    assert (scene["nav"], scene["nav_support"]) == ("这款白色", "头戴耳机，")
    assert cfg["info_card"]["applied"] is True
    assert cfg["info_card"]["original"] == {"gray": "头戴耳机，", "blue": "这款白色"}


def test_independent_eyebrow_keeps_the_template_mapping():
    data = payload(
        title="降噪耳机",
        subtitle="通勤也安静",
        spoken="通勤也安静，这副降噪耳机很好用。",
    )
    before = deepcopy(data["config"]["chapters"])
    out = info_card.apply(data)
    assert out["config"]["chapters"] == before
    assert out["config"]["info_card"]["applied"] is False


def test_other_engines_and_later_scenes_are_untouched():
    capsule = {"template_id": "bihuo-02-v1", "config": {"engine": None, "chapters": []}}
    assert info_card.apply(deepcopy(capsule)) == capsule
    data = payload()
    later = dict(
        at=3.5,
        nav="这款白色",
        nav_support="",
        label="这款白色",
        gray="",
        blue="",
        items=[],
    )
    data["config"]["chapters"].append(later)
    out = info_card.apply(data)
    assert out["config"]["chapters"][1] == later


def test_idempotent():
    once = info_card.apply(payload())
    twice = info_card.apply(deepcopy(once))
    assert twice["config"]["chapters"] == once["config"]["chapters"]
