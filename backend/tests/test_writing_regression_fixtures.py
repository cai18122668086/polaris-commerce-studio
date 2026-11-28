"""The fixed writing regression set (12 scenarios) stays well-formed.

Each scenario is an input a merchant would really type plus what a good run
must and must not produce; ``backend/scripts/writing_eval.py --scenario``
checks finished runs against them. Paid full runs are triggered by hand; this
file only keeps the set itself honest in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent / "fixtures" / "writing_regression"
GOALS = {"store_visit", "product", "promo", "expertise", "peer_share"}
SPEAKERS = {"merchant_self", "visitor", "narrator"}
GENRES = {
    "门店介绍",
    "单品特写",
    "探店体验",
    "选购避坑",
    "活动促销",
    "老板故事",
    "顾客案例",
    "问答",
    "同行经验",
}


def scenarios() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(ROOT.glob("*.json"))
    ]


def test_twelve_scenarios_with_unique_ids() -> None:
    items = scenarios()
    assert len(items) == 12
    assert len({s["id"] for s in items}) == 12
    ids = {s["id"] for s in items}
    # The two the plan names explicitly: the owner's own case and the
    # counter-example whose audience really is other merchants.
    assert {"euro_furniture_store", "furniture_peer_share"} <= ids


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s["id"])
def test_scenario_shape(scenario: dict) -> None:
    assert scenario["schema"] == "tengli.writing-regression/1"
    request, expect = scenario["request"], scenario["expect"]
    assert request["platforms"] and set(request["platforms"]) <= {
        "douyin",
        "xiaohongshu",
    }
    assert 1 <= request["count"] <= 10
    assert request["duration"] in {30, 45, 60, 0}
    assert request["goal"] in GOALS and request["speaker"] in SPEAKERS
    assert len(request["facts_text"]) >= 4
    # An old page always sends a keyword; the new form may leave it empty.
    assert request["legacy_query"].strip()
    assert expect["goal"] == request["goal"]
    assert expect["speaker"] == request["speaker"]
    assert expect["audience"] == (
        "peer" if request["goal"] == "peer_share" else "consumer"
    )
    assert 1 <= len(expect["genres"]) <= 4 and set(expect["genres"]) <= GENRES
    assert expect["category_terms"]
    for side in ("benchmark", "draft"):
        rules = expect["must_not"][side]
        assert rules, side
        for rule in rules:
            assert rule["rule"] and rule["desc"] and rule["terms"]
    assert scenario["notes"]


def test_consumer_scenarios_ban_peer_content_and_peer_one_does_not() -> None:
    for scenario in scenarios():
        benchmark_rules = {r["rule"] for r in scenario["expect"]["must_not"]["benchmark"]}
        if scenario["expect"]["audience"] == "consumer":
            assert "peer" in benchmark_rules, scenario["id"]
        else:
            assert "peer" not in benchmark_rules, scenario["id"]
            assert scenario["expect"].get("expect_peer_benchmarks_min", 0) >= 1


def test_coverage_of_goals_speakers_and_platforms() -> None:
    items = scenarios()
    assert {s["request"]["goal"] for s in items} == GOALS
    assert {s["request"]["speaker"] for s in items} == SPEAKERS
    assert any(not s["request"]["query"] for s in items)  # keyword left empty
    assert any(s["request"]["query"] for s in items)
    assert any(len(s["request"]["platforms"]) == 2 for s in items)
    assert any(s["expect"]["thin_facts"] for s in items)
    assert any(s["request"]["restricted_claims"] for s in items)
