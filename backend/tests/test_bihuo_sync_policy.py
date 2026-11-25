"""bihuo-sync/1: speech-led lead-in, frame flooring, dwell and no overlap."""

import math

import pytest
from PIL import Image

from app.bihuo_suite import layer_timeline, sync_policy
from app.bihuo_suite.sync_policy import (
    BASE_LEAD_S,
    FPS,
    MIN_DWELL_S,
    apply,
    ceil_frame,
    floor_frame,
    lead_seconds,
)
from app.video_quality_check import (
    animating_frames,
    match_targets,
    onset_events,
)


def on_grid(value: float) -> bool:
    return math.isclose(value * FPS, round(value * FPS), abs_tol=1e-6)


def token(ident: str, text: str, start: int, end: int) -> dict:
    return {"id": ident, "text": text, "start_ms": start, "end_ms": end}


def material(asset: str, show_at: str, start: float, span: tuple, end: float) -> dict:
    return {
        "asset_id": asset,
        "path": f"/m/{asset}.png",
        "kind": "image",
        "start": start,
        "end": end,
        "spoken_text": asset,
        "spoken_span": {"text": asset, "start": span[0], "end": span[1]},
        "show_at_token_id": show_at,
        "edge": "end",
    }


def resolved(**extra: object) -> dict:
    base = {
        "tokens": [
            token("t1", "这", 2000, 2200),
            token("t2", "支", 2200, 2400),
            token("t3", "樱花", 2400, 2900),
            token("t4", "72", 6000, 6300),
        ],
        "duration": 12.0,
        "opening_end": 1.77,
        "materials": [],
        "points": [],
        "features": [],
        "chapters": [],
    }
    base.update(extra)
    return base


def test_floor_and_ceil_snap_to_frame_grid_without_rounding_later() -> None:
    assert floor_frame(3.03) == 3.0
    assert floor_frame(3.04) == 3.04  # exact boundary survives float noise
    assert floor_frame(3.0799) == 3.04
    assert ceil_frame(3.01) == 3.04
    assert ceil_frame(3.04) == 3.04


def test_lead_is_base_plus_template_half_entry() -> None:
    assert lead_seconds("bihuo-02-v1", "point") == pytest.approx(BASE_LEAD_S + 0.06)
    assert lead_seconds("bihuo-13-v1", "material") == pytest.approx(BASE_LEAD_S + 0.198)
    assert lead_seconds("unknown", "material") == pytest.approx(
        BASE_LEAD_S + sync_policy.DEFAULT_HALF_S
    )


def test_points_lead_the_phrase_and_land_on_frames() -> None:
    points = [
        {"text": "质地清爽不黏腻，", "start": 3.21, "end": 4.43},
        {"text": "抹开很快吸收，", "start": 4.87, "end": 5.75},
        {"text": "淡淡樱花香能留很久。", "start": 6.19, "end": 7.73},
    ]
    timed, record = apply(resolved(points=points), "bihuo-02-v1")
    lead = lead_seconds("bihuo-02-v1", "point")
    for row, original in zip(timed["points"], points, strict=True):
        assert on_grid(row["start"])
        assert row["start"] == floor_frame(original["start"] - lead)
        assert original["start"] - lead - 1 / FPS < row["start"] <= original["start"]
        assert row["end"] == original["end"] and row["text"] == original["text"]
    assert [t["kind"] for t in record["targets"]] == ["point"] * 3
    assert record["version"] == "bihuo-sync/1"
    assert points[0]["start"] == 3.21  # input is never mutated


def test_point_never_leads_before_previous_phrase_end_or_opening() -> None:
    points = [
        {"text": "一", "start": 1.85, "end": 3.0},
        {"text": "二", "start": 3.05, "end": 4.0},
    ]
    timed, _ = apply(resolved(points=points), "bihuo-02-v1")
    assert timed["points"][0]["start"] >= 1.77
    assert timed["points"][1]["start"] >= 3.0
    assert timed["points"][1]["start"] <= 3.05
    assert all(on_grid(row["start"]) for row in timed["points"])


def test_material_moves_from_inner_word_end_to_phrase_start_with_lead() -> None:
    # Planner anchored at the end of "樱花" (2.9 s); the phrase starts at 2.0 s.
    m = material("a", "t3", 2.9, (2.0, 3.6), 9.0)
    timed, record = apply(resolved(materials=[m]), "bihuo-02-v1")
    out = timed["materials"][0]
    lead = lead_seconds("bihuo-02-v1", "material")
    assert out["start"] == floor_frame(2.0 - lead)
    assert on_grid(out["start"]) and out["edge"] == "start"
    assert record["targets"][0]["speech_start"] == 2.0
    assert record["targets"][0]["lead_s"] == pytest.approx(2.0 - out["start"])


def test_long_phrase_keeps_a_numeric_anchor() -> None:
    m = material("a", "t4", 6.3, (3.0, 7.0), 11.0)
    timed, record = apply(resolved(materials=[m]), "bihuo-02-v1")
    assert record["targets"][0]["speech_start"] == 6.0
    assert timed["materials"][0]["start"] == floor_frame(
        6.0 - lead_seconds("bihuo-02-v1", "material")
    )


def test_materials_hold_until_next_with_min_dwell_and_never_overlap() -> None:
    rows = [
        material("a", "t1", 2.2, (2.0, 2.5), 2.6),
        material("b", "t2", 2.6, (2.6, 3.0), 3.2),  # only 0.6 s after a
        material("c", "t3", 6.0, (5.8, 6.5), 9.0),
    ]
    timed, record = apply(resolved(materials=rows), "bihuo-23-v1")
    out = timed["materials"]
    for current, following in zip(out, out[1:], strict=False):
        assert current["end"] == following["start"]  # hold, no gap, no overlap
        assert following["start"] - current["start"] >= MIN_DWELL_S - 1e-9
        assert current["spoken_span"]["end"] == current["end"]
    assert out[-1]["end"] == 9.0
    assert all(on_grid(row["start"]) and row["start"] < row["end"] for row in out)
    assert out[0]["start"] >= 1.77
    assert record["targets"][0]["allowed_start"] == 2.0  # phrase after opening


def test_phrase_inside_opening_is_allowed_only_after_the_title() -> None:
    m = material("a", "t1", 2.2, (0.35, 2.5), 9.0)
    timed, record = apply(resolved(materials=[m], opening_end=1.64), "bihuo-02-v1")
    assert timed["materials"][0]["start"] == 1.64
    assert record["targets"][0]["speech_start"] == 0.35
    assert record["targets"][0]["allowed_start"] == 1.64


def test_last_material_clamped_inside_body() -> None:
    rows = [
        material("a", "t1", 2.2, (2.0, 2.5), 8.0),
        material("b", "t2", 8.0, (8.0, 8.5), 7.7),  # body ends before the lead
    ]
    timed, record = apply(resolved(materials=rows), "bihuo-02-v1")
    last = timed["materials"][-1]
    assert last["start"] == floor_frame(7.7 - 1 / FPS) < last["end"] == 7.7
    assert record["targets"][1]["visible_start"] == last["start"]


def test_off_policy_records_targets_without_changing_times() -> None:
    m = material("a", "t3", 2.9, (2.0, 3.6), 9.0)
    points = [{"text": "一", "start": 3.21, "end": 4.0}]
    source = resolved(materials=[m], points=points)
    timed, record = apply(source, "bihuo-02-v1", "baseline")
    assert timed is source
    assert record["version"] == "baseline"
    assert apply(source, "bihuo-02-v1", "off")[0] is source
    assert [t["visible_start"] for t in record["targets"]] == [2.9, 3.21]
    assert record["targets"][0]["speech_start"] == 2.0


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        apply(resolved(), "bihuo-02-v1", "bihuo-sync/9")


def test_timeline_and_checker_measure_a_reveal_inside_an_opaque_card(
    tmp_path,
) -> None:
    recorder = layer_timeline.Recorder()
    for n in range(12):
        card = Image.new("RGBA", (240, 240))
        card.paste((255, 255, 255, 255), (24, 24, 216, 216))  # opaque from frame 0
        if n >= 4:  # dark text block fades in over frames 4..7
            ink = round(255 - 200 * min(1, (n - 3) / 4))
            card.paste((ink, ink, ink, 255), (48, 48, 192, 96))
        recorder.frame(
            n,
            (
                Image.new("RGB", (240, 240), (n, 0, 0)),
                {
                    "presenter": Image.new("RGBA", (240, 240), (n, n, n, 255)),
                    "information": card,
                },
            ),
        )
    receipt = recorder.write(tmp_path)
    assert receipt["complete"] and receipt["frames"] == 12
    grids = layer_timeline.load_grids(tmp_path / receipt["grid_file"], 12)
    assert set(grids) == {"information"}  # the source picture is not gridded
    events = onset_events(grids, fps=FPS)
    assert [(e["role"], e["onset_frame"]) for e in events] == [("information", 5)]
    rows = match_targets(
        [{"kind": "point", "index": 0, "speech_start": 0.24, "visible_start": 0.2}],
        events,
    )
    assert rows[0]["gap_s"] == pytest.approx(0.2 - 0.24)
    assert animating_frames(recorder.rows) == {4, 5, 6, 7}


def test_exit_of_previous_image_is_not_the_next_entry() -> None:
    import numpy as np

    frames = 20
    grid = np.zeros((frames, 2, 2, 2), dtype=np.int16)
    grid[:10] = 255  # image A visible, fades out over frames 8..9
    grid[8] = 120
    grid[9] = 0
    for n, a in zip(range(10, 14), (60, 140, 220, 255), strict=True):
        grid[n] = a  # image B fades in, 50% reached at frame 11
    grid[14:] = 255
    card = np.zeros_like(grid)
    card[11:] = 255  # a card entering at the same moment
    events = onset_events({"material": grid, "information": card}, fps=FPS)
    assert ("material", 11) in [(e["role"], e["onset_frame"]) for e in events]
    assert all(e["onset_frame"] != 9 for e in events)
    rows = match_targets(
        [{"kind": "material", "index": 0, "speech_start": 0.5, "visible_start": 0.4}],
        events,
    )
    assert rows[0]["event"]["role"] == "material"
