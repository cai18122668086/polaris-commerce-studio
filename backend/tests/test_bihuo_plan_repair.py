"""成套模板编排：两类常见的模型输出偏差确定性修复（dev 11-28 失败样本，不多花钱）。"""

import json
from pathlib import Path

import pytest

from app.bihuo_suite.planning import repair_provider_shapes
from app.bihuo_suite.planning import verify_plan as _verify
from app.video_editing_apple_pipeline import normalize_suite_output
from app.video_editing_contracts import Transcript

FIXTURES = Path(__file__).parent / "fixtures" / "bihuo_plan_repair"


def _case(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    return data, Transcript.model_validate(data["transcript"])


def verify_plan(raw, transcript, cards, **kwargs):
    """The planning worker's path: provider boundary normalisation, then verify."""
    raw, _ = normalize_suite_output(raw, transcript, features_follow_materials=False)
    return _verify(raw, transcript, cards, allow_mixed_body=True, **kwargs)


def _text(transcript, span):
    index = {w.id: i for i, w in enumerate(transcript.tokens)}
    a, b = index[span["first_token_id"]], index[span["last_token_id"]]
    return "".join(w.text for w in transcript.tokens[a : b + 1])


def test_text_opening_title_binds_to_recorded_words_and_passes_contract():
    data, transcript = _case("opening_text_title")
    assert isinstance(data["content"]["opening"]["title"], str)
    repaired = repair_provider_shapes(data["content"], transcript)
    assert _text(transcript, repaired["opening"]["title"]) == "手比脸老得快。"
    assert "手比脸老得快" in _text(transcript, repaired["opening"]["subtitle"])
    assert isinstance(data["content"]["opening"]["title"], str)  # input untouched
    plan = verify_plan(
        data["content"], transcript, data["cards"], require_semantic_captions=True
    )
    assert plan["opening"]["title"]["first_token_id"]


def test_missing_caption_emphasis_gets_one_lexical_keyword_per_caption():
    data, transcript = _case("no_caption_emphasis")
    with pytest.raises(ValueError, match="keyword emphasis"):
        _strict(data, transcript)  # unchanged contract still rejects the raw output
    repaired = repair_provider_shapes(data["content"], transcript)
    words = [_text(transcript, c["emphasis"][0]) for c in repaired["captions"]]
    assert "办公桌" in words and "耳罩" in words and "手提包，" in words
    assert all(len(w.rstrip("，。")) >= 2 for w in words)
    assert "字幕重点词按原话补齐。" in repaired["warnings"]
    verify_plan(
        data["content"], transcript, data["cards"], require_semantic_captions=True
    )


def _strict(data, transcript):
    from app.bihuo_suite import planning

    original = planning.repair_provider_shapes
    planning.repair_provider_shapes = lambda raw, t: raw
    try:
        verify_plan(
            data["content"], transcript, data["cards"], require_semantic_captions=True
        )
    finally:
        planning.repair_provider_shapes = original


def test_well_formed_and_unrepairable_plans_are_left_to_the_strict_contract():
    data, transcript = _case("short_opening")
    # Opening shorter than 1.6 s with the body starting right after it: moving
    # the opening would move spoken body spans, so nothing is changed.
    assert repair_provider_shapes(data["content"], transcript) is data["content"]
    with pytest.raises(ValueError, match="Opening must allow"):
        verify_plan(
            data["content"], transcript, data["cards"], require_semantic_captions=True
        )
