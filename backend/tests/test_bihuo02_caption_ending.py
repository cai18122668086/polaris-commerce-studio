"""bihuo-02: orphan caption lines merge; the last card stays when nothing follows."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.bihuo_suite import planning, registry
from app.video_editing_contracts import Transcript

FIXTURE = Path(__file__).parent / "fixtures/bihuo02_single_token_feature.json"


def caption_payload(lines):
    return {
        "template_id": "bihuo-02-v1",
        "config": {
            "size": [1080, 1920],
            "fonts": registry.fonts("bihuo-02-v1"),
            "captions": [
                {
                    "first_token_id": "t0",
                    "last_token_id": "t1",
                    "time": [3.03, 4.15],
                    "text": "".join(line["text"] for line in lines),
                    "lines": lines,
                }
            ],
        },
    }


def transcript():
    data = json.loads(FIXTURE.read_text("utf-8"))
    return Transcript.model_validate(data["transcript"])


def test_two_character_line_merges_when_the_caption_fits_one_line():
    payload = caption_payload(
        [
            {"text": "质地", "emphasis_spans": []},
            {"text": "清爽不黏腻，", "emphasis_spans": [[0, 2]]},
        ]
    )
    before = copy.deepcopy(payload)
    fitted = planning._fit_capsule_captions(payload, transcript())
    assert payload == before
    (cue,) = fitted["config"]["captions"]
    assert cue["lines"] == [{"text": "质地清爽不黏腻，", "emphasis_spans": [[2, 4]]}]
    assert cue["text"] == before["config"]["captions"][0]["text"]
    assert fitted["config"]["caption_lines"]["merged"] == ["质地清爽不黏腻，"]
    native = registry.runtime("bihuo-02-v1").capsule
    native.caption(fitted["config"], 3.5)  # the native painter accepts it


def test_balanced_or_too_wide_breaks_stay():
    balanced = caption_payload(
        [
            {"text": "新品上架前，", "emphasis_spans": []},
            {"text": "商品图先检查这三件事。", "emphasis_spans": []},
        ]
    )
    assert planning._fit_capsule_captions(balanced, transcript()) is balanced
    wide = caption_payload(
        [
            {"text": "其实", "emphasis_spans": []},
            {"text": "出门前敲完键盘洗完手都能补一补", "emphasis_spans": []},
        ]
    )
    assert planning._fit_capsule_captions(wide, transcript()) is wide


def ending_payload(title_at, exit_times=(10.774, 11.134), duration=11.134, frames=278):
    return {
        "template_id": "bihuo-02-v1",
        "config": {
            "fps": 25,
            "duration": duration,
            "frame_count": frames,
            "card_exit": list(exit_times),
            "third": {"title_at": title_at},
            "_list_spec": {"events": {"exit": list(exit_times)}},
        },
    }


def test_card_stays_to_the_end_when_the_closing_card_never_starts():
    out = planning._hold_capsule_card(ending_payload(title_at=11.134))
    cfg = out["config"]
    assert cfg["card_exit"][0] > (278 - 1) / 25
    assert cfg["_list_spec"]["events"]["exit"] == cfg["card_exit"]
    assert cfg["capsule_ending"]["held"] is True
    assert cfg["capsule_ending"]["original_exit"] == [10.774, 11.134]


def test_native_exit_stays_when_the_closing_card_starts_inside_the_clip():
    out = planning._hold_capsule_card(
        ending_payload(title_at=8.0, exit_times=(7.5, 7.85))
    )
    assert out["config"]["card_exit"] == [7.5, 7.85]
    assert out["config"]["capsule_ending"]["held"] is False
    other = {**ending_payload(title_at=11.134), "template_id": "bihuo-03-v1"}
    assert planning._hold_capsule_card(copy.deepcopy(other)) == other
