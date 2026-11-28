"""bihuo-frame/1: render-time face safety and overlay dissolves."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.bihuo_suite import frame_policy as fp
from app.bihuo_suite import layer_timeline, subject

W, H = fp.W, fp.H
REPO = Path(__file__).resolve().parents[2]


class StubDetector:
    def __init__(self, box):
        self.box = box

    def detect(self, image):
        return (self.box, 0.9) if self.box else None


def layer(box=None, color=(255, 255, 255, 255)):
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if box:
        ImageDraw.Draw(image).rectangle(
            (box[0], box[1], box[2] - 1, box[3] - 1), fill=color
        )
    return image


def policy(face=(440, 340, 740, 740)):
    p = fp.Policy()
    p.detector = StubDetector(face)
    p.error = None
    return p


def frame(roles):
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for image in roles.values():
        canvas.alpha_composite(image)
    return canvas.convert("RGB"), roles


def test_model_is_vendored_and_pinned():
    assert subject.MODEL.is_file()
    assert subject.model_available()


def test_yunet_finds_the_presenter_face():
    portrait = REPO / "assets/video-studio/owned/presenter-female-v1.png"
    if not portrait.is_file():
        pytest.skip("presenter fixture missing")
    image = Image.open(portrait).convert("RGBA").resize((W, H))
    found = subject.FaceDetector((W, H)).detect(image)
    assert found is not None
    (x0, y0, x1, y1), score = found
    assert score > 0.6
    assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H
    assert 60 < x1 - x0 < 700


def test_face_track_holds_short_misses_and_expires():
    track = subject.FaceTrack(window=10, hold=12)
    assert track.update(0, (10, 10, 20, 20)) == (10, 10, 20, 20)
    assert track.update(1, (12, 12, 22, 22)) == (10, 10, 22, 22)
    assert track.update(5, None) == (10, 10, 22, 22)
    assert track.update(14, None) is None


def test_place_moves_a_card_below_the_face_and_respects_the_caption_band():
    core, safe = (440, 300, 740, 770), (365, 180, 815, 840)
    card = (100, 400, 980, 700)
    s, dy, zone = fp.place(card, core, safe, fp.MARGIN, 1500)
    moved = fp.transform_box(card, ((100 + 980) / 2, 550), s, dy)
    assert zone == "safe"
    assert moved[1] >= safe[3] + fp.GAP - 1 and moved[3] <= 1500 + 1
    assert s == 1.0


def test_place_shrinks_when_no_band_fits_at_full_size():
    core, safe = (440, 300, 740, 1100), (365, 180, 815, 1300)
    card = (100, 400, 980, 900)  # 500 px tall; 200 px free above, 200 below
    found = fp.place(card, core, safe, fp.MARGIN, 1500)
    assert found is None or found[0] < 1.0


def test_no_conflict_returns_the_template_frame_untouched():
    p = policy()
    roles = {
        "background": layer((0, 0, W, H), (20, 20, 20, 255)),
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "topic": layer((250, 120, 830, 260)),
    }
    result = frame(roles)
    assert p.frame(0, result) is result


def test_card_over_the_face_moves_and_only_that_region_changes():
    p = policy()
    roles = {
        "background": layer((0, 0, W, H), (20, 20, 20, 255)),
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "card": layer((150, 420, 930, 700), (250, 250, 250, 255)),
        "caption": layer((200, 1580, 880, 1660)),
    }
    result = frame(roles)
    rgb, adjusted = p.frame(0, result)[:2]
    box = adjusted["card"].getchannel("A").getbbox()
    face = (440, 340, 740, 740)
    assert fp._intersect(box, fp._clip(subject.expand(face, *fp.CORE))) is None
    assert box[3] <= 1580 - fp.GAP + 1  # never into the caption band
    assert adjusted["caption"] is roles["caption"]
    before = np.asarray(result[0], dtype=np.int16)
    after = np.asarray(rgb, dtype=np.int16)
    changed = np.argwhere(np.abs(after - before).max(axis=-1) > 0)
    y0, y1 = changed[:, 0].min(), changed[:, 0].max()
    assert y0 >= 420 - 1 and y1 <= box[3] + 1
    assert p.summary["moves"] and p.summary["moves"][0]["result"] == "clear"


def test_group_moves_together_and_stays_put():
    p = policy()
    roles = {
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "title_plate": layer((260, 500, 820, 700), (200, 200, 200, 255)),
        "title": layer((280, 520, 800, 600)),
        "support": layer((300, 640, 780, 720)),
    }
    first = p.frame(0, frame(roles))[1]
    boxes = {
        k: first[k].getchannel("A").getbbox()
        for k in ("title_plate", "title", "support")
    }
    dy = boxes["title"][1] - 520
    assert dy != 0
    assert boxes["title_plate"][1] - 500 == dy and boxes["support"][1] - 640 == dy
    # Same layout next frame: the decision holds, no oscillation.
    second = p.frame(1, frame(roles))[1]
    assert second["title"].getchannel("A").getbbox() == boxes["title"]


def test_late_conflict_eases_instead_of_jumping():
    p = policy(face=(440, 1100, 740, 1450))
    roles = {
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "card": layer((150, 420, 930, 700)),
    }
    for n in range(4):  # card visible, no conflict yet
        p.frame(n, frame(roles))
    p.detector = StubDetector((440, 340, 740, 740))
    p.track = subject.FaceTrack()
    tops = []
    for n in range(4, 4 + fp.SETTLE_FRAMES + fp.EASE_FRAMES + 3):
        out = p.frame(n, frame(roles))
        tops.append(out[1]["card"].getchannel("A").getbbox()[1])
    steps = np.diff([420, *tops])
    assert (steps >= 0).all() or (steps <= 0).all()
    assert abs(steps).max() < abs(tops[-1] - 420)  # several steps, not one jump
    assert tops[-1] == tops[-2]


def test_full_screen_broll_may_cover_the_face_and_is_recorded():
    p = policy()
    roles = {
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "poster": layer((0, 0, W, H), (180, 120, 60, 255)),
    }
    for n in range(30):
        out = p.frame(n, frame(roles))
        assert out[1]["poster"] is roles["poster"]
    receipt = p.summary
    p.finish(30)
    assert receipt["broll"] and receipt["broll"][0]["seconds"] == pytest.approx(30 / 25)
    assert receipt["broll"][0]["within_limit"]


def test_hard_switch_dissolves_over_four_frames():
    p = policy(face=None)
    red, blue = (230, 40, 30, 255), (30, 40, 230, 255)
    seq = [red] * 3 + [blue] * 6
    reds = []
    for n, color in enumerate(seq):
        roles = {
            "presenter": layer((0, 1200, W, H), (90, 90, 90, 255)),
            "media": layer((100, 200, 980, 900), color),
        }
        out = p.frame(n, frame(roles))
        reds.append(out[0].getpixel((540, 500))[0])
    assert reds[:3] == [230, 230, 230]
    mid = reds[3 : 3 + fp.DISSOLVE_FRAMES]
    assert all(30 < r < 230 for r in mid) and mid == sorted(mid, reverse=True)
    assert reds[-1] == 30
    assert p.summary["dissolves"]["switch"] == 1


def test_hard_removal_fades_out_instead_of_vanishing():
    p = policy(face=None)
    for n in range(3):
        roles = {
            "presenter": layer((0, 1200, W, H), (90, 90, 90, 255)),
            "media": layer((100, 200, 980, 900), (230, 40, 30, 255)),
        }
        p.frame(n, frame(roles))
    seen = []
    for n in range(3, 3 + fp.DISSOLVE_FRAMES + 2):
        roles = {"presenter": layer((0, 1200, W, H), (90, 90, 90, 255))}
        out = p.frame(n, frame(roles))
        seen.append(out[0].getpixel((540, 500))[0])
    assert seen[0] > 0 and seen[-1] == 0
    assert p.summary["dissolves"]["disappear"] == 1


def test_designed_fade_is_left_alone():
    p = policy(face=None)
    for n in range(12):
        a = min(255, n * 32)
        roles = {
            "presenter": layer((0, 1200, W, H), (90, 90, 90, 255)),
            "media": layer((100, 200, 980, 900), (230, 40, 30, a)),
        }
        result = frame(roles)
        assert p.frame(n, result) is result
    assert sum(p.summary["dissolves"].values()) == 0


def test_captions_never_dissolve():
    p = policy(face=None)
    for n in range(8):
        roles = {
            "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
            "caption": layer((200, 1580, 880 if n < 4 else 600, 1660)),
        }
        result = frame(roles)
        assert p.frame(n, result) is result


def test_policy_errors_never_fail_the_render():
    p = policy()

    class Broken:
        def detect(self, image):
            raise RuntimeError("boom")

    p.detector = Broken()
    roles = {"presenter": layer((0, 0, W, H)), "card": layer((150, 420, 930, 700))}
    result = frame(roles)
    assert p.frame(0, result) is result
    assert "boom" in p.error
    assert p.frame(1, result) is result


def test_execution_wraps_only_when_the_config_asks(tmp_path):
    calls = []

    def render_frame(cfg, n):
        calls.append(n)
        return frame({"presenter": layer((0, 0, W, H))})

    module = SimpleNamespace(render_frame=render_frame)
    with fp.execution(module, {"config": {}}) as framing:
        assert framing is None and module.render_frame is render_frame
    payload = {"config": {"frame_policy": {"version": fp.VERSION}}}
    with fp.execution(module, payload) as framing:
        assert module.render_frame is not render_frame
        module.render_frame({}, 0)
        receipt = framing.write(tmp_path)
    assert module.render_frame is render_frame
    assert receipt["version"] == fp.VERSION and receipt["frames"] == 1
    assert (tmp_path / fp.FILENAME).is_file()
    assert fp.unsupported(payload, SimpleNamespace()) == {
        "version": fp.VERSION,
        "complete": False,
        "error": "runtime has no render_frame",
    }


def test_layer_timeline_records_three_tuple_runtimes(tmp_path):
    def render_frame(cfg, n):
        rgb, roles = frame(
            {"presenter": layer((0, 0, W, H)), "card": layer((1, 1, 50, 50))}
        )
        return rgb, roles, {"meta": True}

    module = SimpleNamespace(render_frame=render_frame)
    with layer_timeline.recording(module) as recorder:
        module.render_frame({}, 0)
    receipt = recorder.write(tmp_path)
    assert receipt["complete"]
    assert set(recorder.rows[0]["roles"]) == {"presenter", "card"}


def test_compile_records_the_frame_policy(monkeypatch):
    from app.bihuo_suite import planning

    captured = {}

    def fake_compile(verified, transcript, assets, source, fonts, **kwargs):
        captured["payload"] = kwargs["recipe_compiler"]({"opening_end": 1.0})
        return captured["payload"]

    monkeypatch.setattr(planning, "verify_plan", lambda plan, transcript, cards: plan)
    monkeypatch.setattr(planning.contracts, "verify_plan", lambda *a, **k: None)
    monkeypatch.setattr(planning.contracts, "compile_render_input", fake_compile)
    monkeypatch.setattr(planning, "native_caption_text", lambda timed, v, t: timed)
    monkeypatch.setattr(planning, "_fit_capsule_captions", lambda payload, t: payload)
    monkeypatch.setattr(
        "app.bihuo_suite.conditional_layout.prepare", lambda payload: payload
    )

    def compiler(resolved, **options):
        return {"template_id": "bihuo-08-v1", "config": {}}

    for policy_name, expected in (
        (fp.VERSION, {"version": fp.VERSION}),
        (fp.OFF, None),
    ):
        planning.compile_render_input(
            {},
            SimpleNamespace(),
            {},
            "/tmp/source.mp4",
            {},
            recipe_compiler=compiler,
            template_id="bihuo-08-v1",
            frame_policy=policy_name,
        )
        assert captured["payload"]["config"].get("frame_policy") == expected
    with pytest.raises(ValueError):
        planning.compile_render_input(
            {},
            SimpleNamespace(),
            {},
            "/tmp/source.mp4",
            {},
            recipe_compiler=compiler,
            template_id="bihuo-08-v1",
            frame_policy="bogus",
        )


def test_face_track_drops_history_when_the_presenter_jumps():
    track = subject.FaceTrack(window=10, hold=12)
    track.update(0, (400, 300, 700, 700))
    assert track.update(1, (170, 1000, 290, 1130)) == (170, 1000, 290, 1130)


def test_moved_line_never_lands_on_another_card():
    core, safe = (400, 300, 700, 700), (330, 200, 770, 800)
    title = (96, 120, 984, 237)
    support = (346, 282, 735, 352)
    found = fp.place(support, core, safe, fp.MARGIN, 1500, (title,))
    assert found is not None
    s, dy, _ = found
    moved = fp.transform_box(support, ((346 + 735) / 2, (282 + 352) / 2), s, dy)
    assert not fp._near(moved, title, fp.GAP // 2)
    assert moved[1] >= safe[3]  # below the face, not above the title


def test_face_zone_is_clipped_to_the_presenter_window():
    p = policy(face=(420, 400, 660, 700))
    roles = {
        "presenter": layer((97, 413, 984, 1193), (90, 90, 90, 255)),
        "title_main": layer((96, 120, 984, 237)),
        "title_support": layer((346, 282, 735, 352)),
    }
    result = frame(roles)
    assert p.frame(0, result) is result  # nothing above the window moves


def test_cards_do_not_react_while_the_presenter_sweeps_past():
    p = policy()
    roles = {
        "presenter": layer((0, 0, W, H), (90, 90, 90, 255)),
        "zh_current": layer((130, 1172, 950, 1244)),
    }
    for n in range(20):  # face slides down 40 px per frame through the caption
        top = 600 + 40 * n
        p.detector = StubDetector((470, top, 640, top + 200))
        out = p.frame(n, frame(roles))
        if 3 <= n <= 17:
            assert out[1]["zh_current"] is roles["zh_current"], n
    assert not p.summary["moves"]
