"""bihuo-opening-card/1: bihuo-02 opening title clear of the presenter window."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.bihuo_suite import opening_card
from app.bihuo_suite.registry import fonts, runtime


def config(title="冬天手干？", start=2.6):
    return {
        "size": [1080, 1920],
        "opening_title": title,
        "fonts": {"body": fonts("bihuo-02-v1")["body"]},
        "motion": {"times": [start, start + 0.745], "from": [93, 476, 894, 891]},
    }


def text_rows(layer):
    a = np.asarray(layer)
    ink = (a[..., 3] > 0) & (a[..., :3].max(-1) < 200)
    ys = np.nonzero(ink.any(1))[0]
    return ys.min(), ys.max()


def engine():
    return runtime("bihuo-02-v1").capsule


def test_only_the_capsule_bundle_is_patched():
    assert opening_card._engine(runtime("bihuo-02-v1")) is not None
    for template in ("bihuo-03-v1", "bihuo-04-v1"):  # vendor the file, never run it
        assert opening_card._engine(runtime(template)) is None


def test_title_lands_in_the_visible_strip():
    record = opening_card.Record()
    back = opening_card.rebuild(engine(), config(), 1.0, record)
    top, bottom = text_rows(back)
    assert top > 390 and bottom < 476  # fully above the window's top edge
    assert record.frames == 1 and record.title_y is not None


def test_template_original_title_was_covered():
    e = engine()
    probe = e.blank(config())
    e.text_at(
        probe, "冬天手干？", config()["fonts"]["body"], 34, 120, 461, (80, 80, 80, 255)
    )
    top, bottom = text_rows(probe)
    assert bottom > 476  # the bug this module fixes


def test_nothing_changes_after_the_opening_or_without_a_title():
    record = opening_card.Record()
    assert opening_card.rebuild(engine(), config(), 2.7, record) is None
    assert opening_card.rebuild(engine(), config(title=""), 1.0, record) is None
    assert record.frames == 0


def test_fade_matches_the_template():
    e = engine()
    record = opening_card.Record()
    early = opening_card.rebuild(e, config(), 1.0, record)
    late = opening_card.rebuild(e, config(), 2.5, record)
    assert early.getchannel("A").getextrema()[1] == 255
    assert late.getchannel("A").getextrema()[1] < 255


def test_execution_needs_the_phase2_policy_and_restores_the_engine():
    module = runtime("bihuo-02-v1")
    original = module.capsule.render_layers
    with opening_card.execution(module, {"config": {}}) as record:
        assert record is None and module.capsule.render_layers is original
    payload = {"config": {"frame_policy": {"version": "bihuo-frame/1"}}}
    with opening_card.execution(module, payload) as record:
        assert record is not None and module.capsule.render_layers is not original
    assert module.capsule.render_layers is original
    assert opening_card.execution(SimpleNamespace(), payload).__enter__() is None
