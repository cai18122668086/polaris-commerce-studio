"""Display fixes preserve source wording, clocks and frozen recipe identity."""

import copy
from types import SimpleNamespace

import pytest
from PIL import Image

from app.bihuo_suite import conditional_layout as layout
from app.bihuo_suite import registry


def test_long_no_image_node_keeps_every_character_and_fits_native_width():
    native = registry.runtime("bihuo-03-v1").top
    fonts = registry.fonts("bihuo-03-v1")
    labels = [
        "产品是否清楚，",
        "规格和使用场景有没有讲完整。",
        "颜色和排版是不是统一。",
    ]
    cfg = {
        "size": [1080, 1920],
        "fonts": fonts,
        "materials": [],
        "chapters": [
            {
                "items": [
                    {"text": s, "at": i + 1, "enter_at": i + 0.92, "clear_at": i + 1.24}
                    for i, s in enumerate(labels)
                ]
            }
        ],
    }
    before = copy.deepcopy(cfg)
    payload = layout.prepare({"template_id": "bihuo-03-v1", "config": cfg})
    assert cfg == before
    scene = payload["config"]["chapters"][0]
    for item, original in zip(scene["items"], labels, strict=True):
        display = item["display_horizontal"]
        assert "".join(display["lines"]) == item["text"] == original
        assert 28 <= display["size"] <= 36
        assert len(display["lines"]) <= 3
        assert all(
            native.font(fonts["bold"], display["size"]).getlength(s) <= 198
            for s in display["lines"]
        )
    with layout.execution(registry.runtime("bihuo-03-v1"), payload):
        image = native.step_nodes(payload["config"], 4.0, scene)
    assert image.getbbox()[3] < 1370


def test_no_image_holds_display_without_retiming_speech_or_materials():
    phases = [
        {"entry": [10, 26], "exit": [30, 39], "background_exit": [30, 41]},
        {"entry": [90, 106], "exit": [120, 129], "background_exit": [120, 131]},
    ]
    cfg = {
        "materials": [],
        "phases": phases,
        "frame_count": 250,
        "fade_start": 237,
        "resolved_plan": {"quote_start": 8.0},
        "captions": [
            {"text": "真实原话", "range": [10, 30], "glyph_firsts": [10, 12, 16, 22]}
        ],
    }
    before = copy.deepcopy(cfg)
    result = layout.prepare({"template_id": "bihuo-09-v1", "config": cfg})["config"]
    assert cfg == before
    assert result["captions"] == before["captions"]
    assert result["resolved_plan"] == before["resolved_plan"]
    assert result["phases"][0]["exit"][0] == 90
    assert result["phases"][1]["exit"][0] == 200
    assert result["phases"][0]["spoken_display_events"] == phases[0]


def test_opening_header_and_presenter_do_not_overlap_including_entry_exit():
    module = registry.runtime("bihuo-13-v1")
    cfg = {
        "materials": [],
        "title": "商品图先检查",
        "support": "新品上架前，",
        "title_events": {"entry": [2, 9], "exit": [70, 75]},
        "mode": "replacement",
    }
    payload = layout.prepare({"template_id": "bihuo-13-v1", "config": cfg})
    original = module.E.person_rect
    with layout.execution(module, payload):
        for n in [0, 2, 4, 8, 40, 70, 74]:
            x, y, w, h = module.E.person_rect(payload["config"], n)
            assert y >= 380
            assert y + h == 1652
        assert module.E.person_rect(payload["config"], 100) == original(cfg, 100)
    assert module.E.person_rect is original


def test_photo_header_is_inside_canvas_and_does_not_cover_sharp_photo():
    module = registry.runtime("bihuo-08-v1")
    engine = module.E
    cfg = {
        "mode": "new",
        "fonts": registry.fonts("bihuo-08-v1"),
        "materials": [{"id": "image", "path": "not-read", "start": 75, "end": 190}],
        "_active_material": {
            "id": "image",
            "path": "not-read",
            "start": 75,
            "end": 190,
        },
        "material_texts": ["产品是否清楚，", "使用场景", "颜色和排版"],
    }
    payload = layout.prepare({"template_id": "bihuo-08-v1", "config": cfg})
    observed = []

    def photo(c, n, roles):
        observed.append(c["material_texts"])

    for n in [80, 120, 180]:
        out = {"material_text": Image.new("RGBA", (1080, 1920))}
        layout._photo_text(engine, photo, payload["config"], n, out)
        bounds = out["material_text"].getbbox()
        assert bounds is not None and bounds[1] >= 70 and bounds[3] <= 491
    assert observed == [[], [], []]


def test_hook_restoration_and_old_payloads_are_untouched():
    module = registry.runtime("bihuo-03-v1")
    original = module.top.step_nodes
    payload = {
        "template_id": "bihuo-03-v1",
        "config": {"conditional_layout": layout.identity()},
    }
    with pytest.raises(RuntimeError), layout.execution(module, payload):
        assert module.top.step_nodes is not original
        raise RuntimeError("renderer stopped")
    assert module.top.step_nodes is original
    with layout.execution(SimpleNamespace(), {"config": {}}):
        pass
    for tid in ("bihuo-02-v1", "bihuo-04-v1"):
        old = {"template_id": tid, "config": {"captions": []}}
        assert layout.prepare(old) is old
    payload["config"]["conditional_layout"]["sha256"] = "changed"
    with (
        pytest.raises(ValueError, match="differs from compiled"),
        layout.execution(module, payload),
    ):
        pass
