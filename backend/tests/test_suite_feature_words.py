"""Feature labels stay on whole recorded words (bihuo-02 「支，」 button)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.video_editing_contracts import Transcript
from app.video_planner_policy import _fit_feature_words, normalize_suite_output

FIXTURE = Path(__file__).with_name("fixtures") / "bihuo02_single_token_feature.json"


def saved():
    data = json.loads(FIXTURE.read_text("utf-8"))
    return Transcript.model_validate(data["transcript"]), data["response"]


def words(transcript, row):
    ids = [t.id for t in transcript.tokens]
    a, b = ids.index(row["first_token_id"]), ids.index(row["last_token_id"])
    return "".join(t.text for t in transcript.tokens[a : b + 1])


def test_saved_response_reproduces_the_fragment():
    transcript, raw = saved()
    assert [words(transcript, f) for f in raw["features"]] == ["支，"]


def test_fragment_is_widened_to_its_spoken_clause():
    transcript, raw = saved()
    changed, repairs = normalize_suite_output(raw, transcript)
    assert [words(transcript, f) for f in changed["features"]] == ["随身带一支，"]
    fitted = [r for r in repairs if r["kind"] == "feature_clause_fitted"]
    assert fitted and fitted[0]["text"] == "随身带一支，"
    # Captions are untouched by the label repair.
    assert (
        changed["captions"]
        == normalize_suite_output({**raw, "features": []}, transcript)[0]["captions"]
    )


def test_whole_single_character_word_is_kept():
    transcript, raw = saved()
    ids = [t.id for t in transcript.tokens]
    texts = [t.text for t in transcript.tokens]
    # 「补。」 at the very end is a whole word on its own.
    last = len(texts) - 1
    assert texts[last].startswith("补")
    raw = deepcopy(raw)
    raw["features"] = [{"first_token_id": ids[last], "last_token_id": ids[last]}]
    raw["quote_start_token_id"] = None
    raw["conclusion"] = None
    before = deepcopy(raw["features"])
    positions = {t: i for i, t in enumerate(ids)}
    repairs = _fit_feature_words(raw, transcript, positions)
    assert raw["features"] == before
    assert not [r for r in repairs if r["kind"].startswith("feature_")]


def test_fragment_that_cannot_widen_is_omitted_not_guessed():
    transcript, raw = saved()
    ids = [t.id for t in transcript.tokens]
    raw = deepcopy(raw)
    feature = raw["features"][0]
    position = ids.index(feature["first_token_id"])
    # A point ending right before the fragment leaves no room to widen.
    raw["points"] = [
        *raw["points"][:-1],
        {**raw["points"][-1], "last_token_id": ids[position - 1]},
    ]
    positions = {t: i for i, t in enumerate(ids)}
    repairs = _fit_feature_words(raw, transcript, positions)
    assert raw["features"] == []
    assert repairs[-1]["reason"] == "feature_cuts_a_word"
