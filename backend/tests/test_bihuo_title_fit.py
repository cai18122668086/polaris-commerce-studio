"""Planned titles wider than the suite failed after paid planning (e2e 2026-11-25).

bihuo-09 raised ``Shorter Orange title/support required`` at compile and
bihuo-10 ``Title requires meaningful wrapping`` per frame, both for the saved
title 「这款白色头戴耳机，」 / subtitle 「我在办公桌上」.
"""

import pytest
from PIL import Image

from app.bihuo_suite.registry import definition, fonts, runtime
from app.bihuo_suite.title_fit import fit_inputs, fitted_compiler, word_forms

SAVED = {"title": "这款白色头戴耳机，", "subtitle": "我在办公桌上"}


def bundle(template_id):
    return definition(template_id)["bundle"]


def test_word_forms_never_cut_inside_a_word():
    forms = word_forms("这款白色头戴耳机，")
    assert forms[0] == "这款白色头戴耳机"
    assert "白色头戴耳机" in forms
    assert "款白色头戴耳机" not in forms and "这款白色头" not in forms
    # Same length: keep the head noun rather than the leading words.
    assert forms.index("白色头戴耳机") < forms.index("这款白色头戴")


def test_bihuo09_saved_title_fits_the_orange_compile_check():
    resolved, _, changes = fit_inputs(
        bundle("bihuo-09-v1"), dict(SAVED), None, fonts("bihuo-09-v1")
    )
    engine = runtime("bihuo-09-v1").E
    path = fonts("bihuo-09-v1")["title"]
    assert engine.font(path, 110).getlength(SAVED["title"]) > 925  # The failure.
    assert engine.font(path, 110).getlength(resolved["title"]) <= 925
    assert resolved["title"] == "这款白色头戴耳机"
    assert resolved["subtitle"] == SAVED["subtitle"]
    assert changes == [
        {"field": "title", "from": SAVED["title"], "to": "这款白色头戴耳机"}
    ]


def test_bihuo10_saved_title_fits_the_paper_frame_check():
    resolved, _, _ = fit_inputs(
        bundle("bihuo-10-v1"), dict(SAVED), None, fonts("bihuo-10-v1")
    )
    module = runtime("bihuo-10-v1")
    path = fonts("bihuo-10-v1")["title"]

    def face(text):
        im = module.F.ink(text, path, 100, (255, 255, 255, 255), 0, 0.08)
        return im.rotate(2, resample=Image.Resampling.BICUBIC, expand=True).width

    assert face(SAVED["title"]) > 760  # The render failure.
    assert face(resolved["title"]) <= 760
    assert resolved["title"] == "白色头戴耳机"


def test_user_title_override_is_fitted_too():
    _, options, _ = fit_inputs(
        bundle("bihuo-10-v1"),
        {"title": "短标题"},
        {"title": "这款白色头戴耳机真的很好用"},
        fonts("bihuo-10-v1"),
    )
    assert options is not None and len(options["title"]) < 13


def test_compile_rejection_shortens_at_word_boundary_and_retries():
    seen = []

    def compiler(template_id, resolved, **kwargs):
        seen.append(resolved["title"])
        if len(resolved["title"]) > 4:
            raise ValueError("Title needs shorter wording")
        return {"template_id": template_id, "config": {"title": resolved["title"]}}

    wrapped = fitted_compiler(compiler, lambda _: "no-rules")
    result = wrapped("bihuo-36-v1", {"title": "这款白色头戴耳机"}, creative_options={})
    assert result["config"]["title"] in {"白色头戴", "头戴耳机", "这款白色"}
    assert all(t in "这款白色头戴耳机" for t in seen)


def test_unrelated_compile_errors_are_not_swallowed():
    def compiler(template_id, resolved, **kwargs):
        raise ValueError("Material SHA changed")

    with pytest.raises(ValueError, match="Material SHA changed"):
        fitted_compiler(compiler, lambda _: "no-rules")(
            "bihuo-36-v1", {"title": "这款白色头戴耳机"}, creative_options={}
        )
