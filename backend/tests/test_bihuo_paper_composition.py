"""Mixed paper scenes must not inherit a layout from their ordinal slot."""

import copy

import pytest
from PIL import Image

from app.bihuo_suite import conditional_layout as layout
from app.bihuo_suite import registry


def paper_cfg(tmp_path, *, slot=3, image=True, size=(1800, 962)):
    path = tmp_path / "upload.png"
    Image.new("RGB", size, (20, 100, 210)).save(path)
    phases = [
        dict(
            id=f"p{i}",
            enabled=False,
            asset_id=None,
            note_title="",
            note_detail="",
            example="",
            entry=[10, 26],
            exit=[90, 99],
            background_entry=[3, 9],
            background_exit=[90, 101],
            person_entry=[4, 26],
        )
        for i in range(slot + 1)
    ]
    phases[slot].update(
        enabled=True,
        asset_id="upload" if image else None,
        note_title="产品展示整体配色",
        note_detail="",
    )
    return dict(
        mode="replacement",
        duration=8,
        frame_count=200,
        fade_start=187,
        black_at=199,
        source="not-read",
        fonts=registry.fonts("bihuo-09-v1"),
        materials=[dict(id="upload", path=str(path), semantic_segment=slot)]
        if image
        else [],
        selected_asset_ids=["upload"] if image else [],
        phases=phases,
        resolved_plan={"quote_start": 6},
        body_size=64,
        caption_baseline=1640,
        caption_line_gap=124,
        captions=[
            dict(
                id="cue",
                text="产品展示整体配色都给你安排上了，",
                range=[20, 150],
                glyph_firsts=list(range(20, 36)),
                emphasis_spans=[],
                line_breaks=[],
            )
        ],
    )


@pytest.mark.parametrize("slot", [0, 1, 2, 3, 4])
def test_landscape_upload_fills_the_stage_regardless_of_slot(tmp_path, slot):
    engine = registry.runtime("bihuo-09-v1").E
    cfg = layout.prepare(
        {"template_id": "bihuo-09-v1", "config": paper_cfg(tmp_path, slot=slot)}
    )["config"]
    roles, metrics = layout._material_headers(engine, engine.materials, cfg, 50)
    bounds = roles[f"material_{slot}"].getbbox()
    assert bounds is not None and bounds[2] - bounds[0] >= 968
    assert (bounds[2] - bounds[0]) / (bounds[3] - bounds[1]) == pytest.approx(
        1800 / 962, abs=0.015
    )
    header = roles[f"info_text_{slot}"].getbbox()
    assert header is not None and header[3] < bounds[1]
    assert metrics[0]["fit"] == "contain"


def test_mixed_upload_and_text_scene_uses_compact_panel_and_separate_person(tmp_path):
    engine = registry.runtime("bihuo-09-v1").E
    cfg = paper_cfg(tmp_path, slot=5, image=False)
    # An earlier uploaded scene must not force later text into an empty photo card.
    cfg["materials"] = [
        {"id": "earlier", "path": str(tmp_path / "upload.png"), "semantic_segment": 0}
    ]
    cfg["selected_asset_ids"] = ["earlier"]
    cfg["phases"][0].update(
        enabled=True,
        asset_id="earlier",
        entry=[0, 2],
        exit=[3, 4],
        background_exit=[3, 5],
    )
    original = copy.deepcopy(cfg)
    cfg = layout.prepare({"template_id": "bihuo-09-v1", "config": cfg})["config"]
    roles, metrics = layout._material_headers(engine, engine.materials, cfg, 50)
    panel = roles["info_plate_5"].getbbox()
    words = roles["info_text_5"].getbbox()
    assert panel is not None and panel[2] - panel[0] < 500 and panel[3] - panel[1] < 400
    x, y, w, h = layout._paper_pose(engine, cfg, 50)[0]
    assert x + w < panel[0] and words is not None and words[0] >= panel[0]
    assert (
        cfg["captions"] == original["captions"]
        and cfg["resolved_plan"] == original["resolved_plan"]
    )
    assert cfg["phases"][5]["exit"][0] == 150
    assert metrics[-1]["text_without_image"]


@pytest.mark.parametrize("size", [(720, 1280), (1200, 1200), (1800, 962)])
def test_media_shape_is_preserved_without_crop(tmp_path, size):
    engine = registry.runtime("bihuo-09-v1").E
    cfg = layout.prepare(
        {"template_id": "bihuo-09-v1", "config": paper_cfg(tmp_path, size=size)}
    )["config"]
    roles, _ = layout._material_headers(engine, engine.materials, cfg, 50)
    x, y, x2, y2 = roles["material_3"].getbbox()
    assert (x2 - x) / (y2 - y) == pytest.approx(size[0] / size[1], abs=0.015)
    assert 40 <= x < x2 <= 1040 and 380 <= y < y2 <= 1360


def test_subtitle_wrap_improves_anchor_without_changing_words_or_fa(tmp_path):
    cfg = paper_cfg(tmp_path)
    before = copy.deepcopy(cfg["captions"])
    result = layout.prepare({"template_id": "bihuo-09-v1", "config": cfg})["config"]
    display = result["conditional_layout"]["paper_caption_layouts"]["cue"]
    assert display["size"] == 80 and display["line_breaks"]
    assert result["captions"] == before
    for start, end in zip(
        [0, *display["line_breaks"]],
        [*display["line_breaks"], len(before[0]["text"])],
        strict=True,
    ):
        assert (
            registry.runtime("bihuo-09-v1")
            .E.font(cfg["fonts"]["body"], display["size"])
            .getlength(before[0]["text"][start:end])
            <= 920
        )


def test_subtitle_baseline_is_stable_through_person_and_card_transitions(tmp_path):
    engine = registry.runtime("bihuo-09-v1").E
    cfg = layout.prepare({"template_id": "bihuo-09-v1", "config": paper_cfg(tmp_path)})[
        "config"
    ]
    for n in (20, 26, 50, 90, 99, 110):
        layers, meta = layout._paper_captions(engine, cfg, n)
        assert meta["baseline"] == 1640
        caption = layers["caption"].getbbox()
        x, y, w, h = layout._paper_pose(engine, cfg, n)[0]
        assert caption is not None and caption[1] > y + h


def test_long_text_card_fits_all_recorded_words(tmp_path):
    engine = registry.runtime("bihuo-09-v1").E
    cfg = paper_cfg(tmp_path, slot=5, image=False)
    cfg["phases"][5].update(
        note_title="再从详情图里选好想参考的风格，点击生成，",
        note_detail="一组套用了咱们自己产品的商品图就做好了。",
    )
    prepared = layout.prepare({"template_id": "bihuo-09-v1", "config": cfg})
    roles, _ = layout._material_headers(
        engine, engine.materials, prepared["config"], 50
    )
    words = roles["info_text_5"].getbbox()
    panel = roles["info_plate_5"].getbbox()
    assert words is not None and panel is not None
    assert panel[0] <= words[0] < words[2] <= panel[2]
    assert panel[1] <= words[1] < words[3] <= panel[3]
    assert (
        prepared["config"]["phases"][5]["note_title"] == cfg["phases"][5]["note_title"]
    )
    assert (
        prepared["config"]["phases"][5]["note_detail"]
        == cfg["phases"][5]["note_detail"]
    )
