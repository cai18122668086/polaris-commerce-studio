"""Display fixes preserve source wording, clocks and frozen recipe identity."""

import copy
from types import SimpleNamespace

import pytest
from PIL import Image

from app.bihuo_suite import conditional_layout as layout
from app.bihuo_suite import registry


def test_silver_font_fit_preserves_words_clocks_and_restores_compile_hook():
    from app.bihuo_suite import adaptive_layout

    engine = registry.runtime("bihuo-36-v1").E
    cfg = {"fonts": registry.fonts("bihuo-36-v1"), "white_size": 76, "gold_size": 82}
    cue = {
        "text": "产品展示整体配色都给你安排上了",
        "emphasis_spans": [],
        "range": [100, 150],
    }
    before = copy.deepcopy((cfg, cue))
    received = []
    adaptive_layout.silver_whole_line(
        engine, lambda c, v: received.append((c, v)), cfg, cue
    )
    assert (cfg, cue) == before
    shown = received[0][1]
    # Fits by a smaller size (same cue), or is laid out as lines of the same words.
    assert shown is cue or "".join(row["text"] for row in shown["lines"]) == cue["text"]
    assert 70 <= received[0][0]["white_size"] <= 76
    original = engine.whole_line
    with pytest.raises(RuntimeError), adaptive_layout.compilation("bihuo-36-v1"):
        assert engine.whole_line is not original
        raise RuntimeError("compile interrupted")
    assert engine.whole_line is original


def test_silver_overlong_line_splits_at_punctuation_keeping_words_and_emphasis():
    """居中字幕：长句缩字号仍超宽时拆成两行，原文、重点词与时间不变（不再整片失败）。"""
    from app.bihuo_suite import adaptive_layout

    engine = registry.runtime("bihuo-36-v1").E
    cfg = {"fonts": registry.fonts("bihuo-36-v1"), "white_size": 76, "gold_size": 82}
    text = "所以挑家具这件事，得先把标准想清楚一点再去门店慢慢挑"
    cue = {"text": text, "emphasis_spans": [[3, 5], [12, 14]], "range": [100, 160]}
    before = copy.deepcopy((cfg, cue))
    received = []
    adaptive_layout.silver_whole_line(
        engine, lambda c, v: received.append((c, v)), cfg, cue
    )
    assert (cfg, cue) == before
    local, shown = received[0]
    rows = shown["lines"]
    assert "".join(row["text"] for row in rows) == text
    assert len(rows) in (2, 3) and shown["range"] == [100, 160]
    marked = [row["text"][a:b] for row in rows for a, b in row["emphasis_spans"]]
    assert marked == ["家具", "标准"]
    for row in rows:
        width = sum(
            engine.font(
                cfg["fonts"]["caption"],
                local["gold_size"] if active else local["white_size"],
            ).getlength(part)
            for part, active in engine.visual.caption_parts({**shown, **row})
        )
        assert width <= adaptive_layout.SILVER_MAX_WIDTH


def test_split_never_cuts_inside_an_emphasis_span():
    from app.bihuo_suite.adaptive_layout import split_caption_line

    line = {"text": "一二三四五六七八", "emphasis_spans": [[2, 6]]}
    rows = split_caption_line(line, 2)
    assert rows is not None
    assert all(len(row["emphasis_spans"]) <= 1 for row in rows)
    assert "".join(row["text"] for row in rows) == "一二三四五六七八"
    assert sum(len(row["emphasis_spans"]) for row in rows) == 1


def test_paper_card_wraps_actual_long_items_without_changing_their_text_or_clocks():
    module = registry.runtime("bihuo-10-v1")
    cfg = {
        "fonts": module.core._style_fonts(registry.fonts("bihuo-10-v1")),
        "card": {
            "enabled": True,
            "title": "反复改设计",
            "entry": 33.3,
            "exit": [51.92, 52.12],
            "links": [39.72, 40.12],
            "button": "不会设计，",
            "button_at": 40.32,
            "items": [
                {"text": text, "at": at}
                for text, at in [
                    ("卖点排版、", 33.3),
                    ("产品展示整体配色", 34.38),
                    ("逐张查看和调整，", 38.52),
                ]
            ],
        },
    }
    before = copy.deepcopy(cfg)
    with pytest.raises(ValueError, match="semantic wrap"):
        module.C.card_layers(42, cfg)
    payload = layout.prepare({"template_id": "bihuo-10-v1", "config": cfg})
    with layout.execution(module, payload):
        result = module.C.card_layers(42, payload["config"])
        assert result["card-items"].getbbox() is not None
    assert cfg == before


def test_paper_video_cache_is_bounded_and_invisible_media_is_not_painted(tmp_path):
    folder = tmp_path / "frames"
    static = str(tmp_path / "static.png")
    cache = {static: object()}
    received = []
    phases = [
        dict(
            note_title="",
            note_detail="",
            example="",
            background_entry=[a, a + 2],
            background_exit=[a + 8, a + 10],
        )
        for a in (0, 20)
    ]
    cfg = {
        "phases": phases,
        "materials": [
            {"semantic_segment": 0, "path": str(folder / "0.jpg")},
            {"semantic_segment": 1, "path": static},
        ],
        "video_materials": {"streams": [{"frames": [{"path": str(folder / "0.jpg")}]}]},
    }
    native = SimpleNamespace(
        M=SimpleNamespace(_IMAGES=cache),
        out=lambda a, b, n: float(n >= b),
        ease=lambda a, b, n: float(n >= b),
        phase=lambda c, i, n: 0,
        asset=lambda c, i: c["materials"][i],
    )

    def paint(config, frame):
        received.append([m["semantic_segment"] for m in config["materials"]])
        for material in config["materials"]:
            cache[material["path"]] = object()
        return {}, []

    for frame in range(100):
        cfg["materials"][0]["path"] = str(folder / f"{frame}.jpg")
        layout._material_headers(native, paint, cfg, 5)
        assert len(cache) == 2
        assert static in cache
    assert all(items == [0] for items in received)
    assert len(cfg["materials"]) == 2
    layout._material_headers(native, paint, cfg, 40)
    assert received[-1] == []


def video_config(tmp_path):
    from app.bihuo_suite import video_materials
    from app.motion_library import sha256

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"source-bound-video-test")
    rows = []
    for i, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"frame-{i}.png"
        Image.new("RGB", (40, 30), color).save(path)
        rows.append({"path": str(path), "sha256": sha256(path)})
    proxy = str(tmp_path / "slot.jpg")
    policy = {
        **video_materials.identity(),
        "streams": [
            {
                "source_path": str(clip),
                "source_sha256": sha256(clip),
                "proxy_path": proxy,
                "start": 2.0,
                "frames": rows,
            }
        ],
    }
    return {
        "materials": [{"path": proxy}],
        "video_materials": policy,
        "resolved_plan": {"kind": "video", "path": str(clip)},
    }


def test_video_advances_from_slot_start_and_holds_last_frame(tmp_path):
    from app.bihuo_suite.video_materials import VideoFrames

    cfg = video_config(tmp_path)
    frames = VideoFrames(cfg)
    paths = [frames.bind(cfg, n)["materials"][0]["path"] for n in (0, 50, 51, 52, 100)]
    expected = [r["path"] for r in cfg["video_materials"]["streams"][0]["frames"]]
    assert paths == [expected[0], expected[0], expected[1], expected[2], expected[2]]
    assert frames.bind(cfg, 51)["resolved_plan"] == cfg["resolved_plan"]
    assert cfg["materials"][0]["path"].endswith("slot.jpg")
    Image.new("RGB", (40, 30), "yellow").save(expected[2])
    with pytest.raises(ValueError, match="frame changed"):
        VideoFrames(cfg).bind(cfg, 52)


@pytest.mark.parametrize("hook", ["render_frame", "render_layers", "encode"])
def test_timed_video_hooks_restore_and_do_not_freeze_the_first_frame(tmp_path, hook):
    from app.bihuo_suite.video_materials import execution

    cfg = video_config(tmp_path)
    if hook == "encode":
        namespace = {"render": lambda raw, c, n: c["materials"][0]["path"]}
        exec("def encode(c, out): return render(None, c, 51)", namespace)
        module = SimpleNamespace(encode=namespace["encode"])
        original = namespace["render"]

        def call():
            return module.encode(cfg, None)
    else:

        def original(c, n):
            return c["materials"][0]["path"]

        module = SimpleNamespace(**{hook: original})

        def call():
            return getattr(module, hook)(cfg, 51)

    with execution(module, {"config": cfg}):
        assert call().endswith("frame-1.png")
    assert (
        namespace["render"] if hook == "encode" else getattr(module, hook)
    ) is original


def test_all_styles_expose_video_without_mutating_native_identity():
    from app.bihuo_suite.video_materials import capabilities

    for template_id, meta in registry.definitions().items():
        before = copy.deepcopy(meta)
        effective = capabilities(meta)
        assert effective.count("video_materials") == 1, template_id
        assert [value for value in effective if value != "video_materials"] == [
            value for value in before["capabilities"] if value != "video_materials"
        ], template_id
        assert meta == before, template_id


def test_frame_extraction_uses_real_video_and_reuses_existing_cache(tmp_path):
    import subprocess

    import imageio_ffmpeg

    from app.bihuo_suite.video_materials import _frames
    from app.config import Settings
    from app.motion_library import sha256

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clip = tmp_path / "moving.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=96x64:rate=25",
            "-t",
            "0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    settings = Settings(video_editing_ffmpeg=ffmpeg)
    material = {"path": str(clip), "sha256": sha256(clip), "duration": 0.4}
    cache = _frames(material, 2.0, tmp_path, settings, lambda: None)
    assert len(cache["frames"]) == 10
    assert cache["frames"][0]["sha256"] != cache["frames"][-1]["sha256"]
    assert _frames(material, 2.0, tmp_path, settings, lambda: None) == cache


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
        "fonts": registry.fonts("bihuo-09-v1"),
        "captions": [
            {
                "id": "cue",
                "text": "真实原话",
                "range": [10, 30],
                "glyph_firsts": [10, 12, 16, 22],
            }
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
    for tid in ("bihuo-02-v1", "bihuo-24-v1"):
        old = {"template_id": tid, "config": {"captions": []}}
        assert layout.prepare(old) is old
    payload["config"]["conditional_layout"]["sha256"] = "changed"
    with (
        pytest.raises(ValueError, match="differs from compiled"),
        layout.execution(module, payload),
    ):
        pass


def test_split_prefers_the_comma_then_falls_back_to_balance():
    from app.bihuo_suite.adaptive_layout import split_caption_line

    line = {"text": "所以挑家具这件事，得先把标准想清楚", "emphasis_spans": []}
    first, _ = split_caption_line(line, 2)
    assert first["text"] == "所以挑家具这件事，"
    first, second = split_caption_line(line, 2, prefer_punctuation=False)
    assert abs(len(first["text"]) - len(second["text"])) <= 1
