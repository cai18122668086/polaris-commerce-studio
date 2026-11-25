"""R2-07: fact drafts rejected by false-positive evidence rules (real 3112 inputs)."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import video_writing_provider as provider
from app.video_writing_contracts import (
    WritingAnalysis,
    WritingFacts,
    WritingReference,
    WritingStructureDraft,
)

DATA = json.loads(
    (Path(__file__).parent / "fixtures/writing_fact_draft_hand_cream.json").read_text(
        "utf-8"
    )
)


def check(draft):
    return provider.validate_draft(
        WritingStructureDraft.model_validate(draft),
        WritingReference.model_validate(DATA["reference"]),
        WritingFacts.model_validate(DATA["facts"]),
        WritingAnalysis.model_validate(DATA["analysis"]),
    )


def variant(**changes):
    draft = copy.deepcopy(DATA["accepted_draft"])
    for key, value in changes.items():
        draft[key] = value
    return draft


def test_the_accepted_real_draft_still_passes():
    assert "樱花香护手霜" in check(DATA["accepted_draft"])


@pytest.mark.parametrize(
    ("original", "replacement", "fact_id"),
    [("护手霜", "樱花香护手霜", "f1"), ("樱花", "淡淡樱花香", "f2")],
)
def test_source_wording_inside_the_users_own_fact_is_not_a_leftover(
    original, replacement, fact_id
):
    row = {
        "category": "product",
        "original": original,
        "replacement": replacement,
        "fact_id": fact_id,
    }
    check(variant(replacements=[row]))


def test_single_counts_are_spoken_measure_words_not_quantity_claims():
    draft = variant()
    draft["sentences"][0]["text"] = "冬天手干，包里备一个护手霜，再放一瓶也不占地方。"
    check(draft)


@pytest.mark.parametrize("bad", ["price", "quantity", "leftover", "skip_section"])
def test_real_violations_are_still_rejected(bad):
    draft = variant()
    if bad == "price":
        draft["sentences"][0]["text"] = "56块钱买这个牌子的护手霜，真的好香。"
    elif bad == "quantity":
        draft["sentences"][0]["text"] = "一次买两瓶更划算。"
    elif bad == "leftover":
        draft["replacements"] = [
            {
                "category": "story",
                "original": "盒子也很漂亮",
                "replacement": "清爽不黏腻",
                "fact_id": "f3",
            }
        ]
        draft["sentences"][1]["text"] += "盒子也很漂亮。"
    else:
        draft["sentences"] = [
            s
            for s in draft["sentences"]
            if s["analysis_section_id"] != "packaging_gift"
        ]
    with pytest.raises(ValueError):
        check(draft)


def test_rejected_output_and_failed_rule_are_kept_for_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "verify_writing_package", lambda _: {})
    draft = variant()
    draft["sentences"][0]["text"] = "一次买两瓶更划算。"
    content = json.dumps(draft, ensure_ascii=False)
    task_id = "3e95373e-8d6f-4751-b535-2041bd3a5c1a"
    service = SimpleNamespace(
        settings=SimpleNamespace(
            video_writing_workflow_enabled=True,
            video_writing_library_dir=tmp_path,
            video_script_model="deepseek-v4.1-flash-1017",
            video_editing_tasks_dir=tmp_path,
        ),
        request=lambda *_, **__: {"choices": [{"message": {"content": content}}]},
    )
    inputs = {
        "reference": DATA["reference"],
        "facts": DATA["facts"],
        "analysis": DATA["analysis"],
        "draft_mode": "structure",
        "writing_task_id": task_id,
    }
    result, _ = provider.plan_writing(service, "fact_draft", inputs)  # type: ignore[arg-type]
    assert result["validation_error"] == "VIDEO_WRITING_EVIDENCE_INVALID"
    assert "numeric claim" in result["validation_detail"]
    saved = json.loads(
        (tmp_path / "_writing" / task_id / "rejected-response.json").read_text("utf-8")
    )
    assert saved["content"] == content and "numeric claim" in saved["error"]
