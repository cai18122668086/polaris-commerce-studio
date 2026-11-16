"""Display fixes preserve source wording, clocks and frozen recipe identity."""

import copy
from types import SimpleNamespace

import pytest
from PIL import Image

from app.bihuo_suite import conditional_layout as layout
from app.bihuo_suite import registry


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


def test_picture_styles_expose_video_without_mutating_native_identity():
    from app.bihuo_suite.video_materials import capabilities

    for meta in registry.definitions().values():
        before = copy.deepcopy(meta)
        effective = capabilities(meta)
        assert ("video_materials" in effective) == ("images" in effective)
        assert meta == before


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
