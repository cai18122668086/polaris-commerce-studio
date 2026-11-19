from pathlib import Path

import json
from hashlib import sha256

from app import video_editing_suite_music as music
from app.bihuo_suite.registry import definitions
from app.config import Settings
from app.video_editing_sound_palettes import PALETTES, select_sound
from app.video_editing_suite_actions import SUITE_FAMILIES, suite_actions
from app.video_editing_suite_music import SUITE_MUSIC
from app.video_editing_suite_sound import enhance_suite_sound


def test_every_bihuo_suite_has_a_bounded_sound_palette():
    assert SUITE_FAMILIES.keys() == definitions().keys()
    assert SUITE_MUSIC.keys() == SUITE_FAMILIES.keys()
    sizes = {
        family: len({row[0] for candidates in actions.values() for row in candidates})
        for family, actions in PALETTES.items()
    }
    assert sizes == {"news": 12, "application": 16, "lifestyle": 12}
    cues = [
        select_sound("application", "media", "stable", occurrence)
        for occurrence in range(4)
    ]
    assert len(set(cues[:3])) == 3
    assert cues[0] == cues[3]


def test_quiet_speech_lowers_the_music_baseline_before_ducking(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, video_editing_tasks_dir=tmp_path)
    source = b"private soundtrack fixture"
    track = music.SuiteMusic(
        "fixture",
        "fixture.mp3",
        sha256(source).hexdigest(),
        0,
        0.2,
        -12,
    )
    monkeypatch.setitem(music.SUITE_MUSIC, "bihuo-47-v1", track)
    asset = music.music_file(settings, track)
    asset.parent.mkdir()
    asset.write_bytes(source)
    measurements = iter(["-17", "-32", "-inf"])

    def fake_run(arguments, root, settings, guard, name):
        log = root / "meter.log"
        if name == "measure_suite_speech":
            log.write_text(json.dumps({"input_i": next(measurements)}), encoding="utf8")
        else:
            (root / "final.mp4").touch()
        return log

    monkeypatch.setattr(music, "run", fake_run)
    results = []
    for label in ("normal", "quiet", "silent"):
        _, result = music.mix_suite_music(
            tmp_path / "master.mp4",
            tmp_path / "speech.wav",
            "bihuo-47-v1",
            "template",
            10000,
            tmp_path / label,
            settings,
            lambda: None,
        )
        results.append(result)
    normal, quiet, silent = results
    assert quiet["gain_db"] <= normal["gain_db"] - 10
    assert quiet["speech_ducking"] is True
    assert silent["speech_lufs"] is None
    json.dumps(silent, allow_nan=False)


def test_native_sound_follows_the_visible_paper_and_picture_clocks():
    paper = suite_actions(
        "bihuo-09-v1",
        {
            "fps": 25,
            "materials": [{"id": "picture"}],
            "phases": [
                {"enabled": True, "entry": [75, 91], "asset_id": "picture"},
                {"enabled": False, "entry": [100, 116], "asset_id": "hidden"},
            ],
        },
    )
    business = suite_actions(
        "bihuo-47-v1",
        {
            "fps": 25,
            "materials": [{"start": 2.0, "visual_start": 3.2}],
            "captions": [{"time": [1.2, 1.8], "lines": [{"emphasis_spans": []}]}],
            "columns": [],
            "star_count": 0,
        },
    )
    assert [at for at, action in paper if action == "media"] == [76 / 25]
    assert [at for at, action in business if action == "media"] == [3.2]
    assert all(action != "emphasis" for _, action in business)


def test_caption_changes_never_add_a_sound():
    for template_id, cfg in (
        ("bihuo-47-v1", {"columns": [], "star_count": 0}),
        ("bihuo-32-v1", {"glyph_caption_ids": ["caption"]}),
    ):
        assert (
            suite_actions(
                template_id,
                {
                    **cfg,
                    "captions": [
                        {"id": "caption", "time": [2, 4], "emphasis": "highlight"},
                        {"range": [30, 40], "bold": True},
                    ],
                },
            )
            == []
        )


def test_fullscreen_recording_silences_the_native_effect_hidden_behind_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.video_editing_suite_sound.run", lambda *_: None)
    monkeypatch.setattr(
        "app.video_editing_suite_sound.write_cue_track", lambda *_: None
    )
    _, sound = enhance_suite_sound(
        Path("base.mp4"),
        {
            "template_id": "bihuo-47-v1",
            "config": {
                "fps": 25,
                "iris_at": 2,
                "columns": [{"start": 4}, {"start": 6}],
                "star_count": 0,
            },
        },
        8000,
        "fixture",
        tmp_path,
        type("Settings", (), {"video_editing_ffmpeg": "ffmpeg"})(),
        lambda: None,
        scan_recordings=False,
        tutorial_clock={
            "holds": [{"source_ms": 3000, "duration_ms": 1000}],
            "steps": [{"large_start_ms": 4800, "end_ms": 6500}],
        },
    )
    assert [(event["at_ms"], event["action"]) for event in sound["events"]] == [
        (2000, "transition"),
        (6000, "text"),
    ]


def test_business_flower_text_and_sparkles_use_individual_visible_starts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.video_editing_suite_sound.run", lambda *_: None)
    monkeypatch.setattr(
        "app.video_editing_suite_sound.write_cue_track", lambda *_: None
    )
    _, sound = enhance_suite_sound(
        Path("base.mp4"),
        {
            "template_id": "bihuo-47-v1",
            "config": {
                "fps": 25,
                "opening_end": 2,
                "title": "Title",
                "support": "Support",
                "identity": {"enabled": True, "name": "Name"},
                "columns": [],
                "star_count": 10,
                "stars_at": 5,
            },
        },
        8000,
        "fixture",
        tmp_path,
        type("Settings", (), {"video_editing_ffmpeg": "ffmpeg"})(),
        lambda: None,
        scan_recordings=False,
        tutorial_clock={
            "holds": [],
            "steps": [{"large_start_ms": 4500, "end_ms": 5400}],
        },
    )
    assert [(event["at_ms"], event["action"]) for event in sound["events"]] == [
        (80, "type"),
        (160, "text"),
        (880, "type"),
        (5400, "confirm"),
    ]
