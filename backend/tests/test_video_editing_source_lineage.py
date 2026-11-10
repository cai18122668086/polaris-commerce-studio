"""Verified handoff references and diagnostics are separate from the audio used."""

from pathlib import Path
from struct import pack
from uuid import uuid4
from wave import open as open_wave

import pytest

from app.config import Settings
from app.errors import ApiError
from app.motion_library import sha256
from app.video_editing_native_frame_clock import variable_frame_clock
from app.video_editing_pipeline import EditingFailure, prepare
from app.video_editing_source_lineage import (
    audio_clock,
    freeze_generation_source,
    generation_source_receipt,
    script_reference,
)
from app.video_generation_models import VideoGenerationRecord
from app.video_studio_models import VideoScriptVersionRecord
from app.video_writing_provenance import matching_writing_origin, script_digest


def test_frame_clock_detects_drift_even_when_the_average_rate_matches():
    def measured(*values: int) -> list[dict[str, int]]:
        return [{"best_effort_timestamp": value} for value in values]

    assert variable_frame_clock(measured(0, 33, 67, 100), "1/1000", "30/1") == (
        4,
        False,
    )
    assert variable_frame_clock(measured(0, 20, 60, 100), "1/1000", "30/1") == (4, True)
    assert variable_frame_clock(measured(0, 33, 67, 100), "1/1000", "24/1") == (4, True)
    with pytest.raises(ValueError, match="must increase"):
        variable_frame_clock(measured(0, 33, 33, 100), "1/1000", "30/1")


def test_generation_snapshot_must_match_the_original_project_confirmation(tmp_path):
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"voice")
    draft = {"drive": "text", "text": "原来确认的口播"}
    version = VideoScriptVersionRecord(
        id="v1", project_id="p1", kind="confirmed", snapshot={"draft": draft}
    )
    job = VideoGenerationRecord(
        project_id="p1",
        confirmed_version_id="v1",
        details={"snapshot": {"draft": draft.copy()}, "audio_local_path": str(voice)},
    )
    frozen = freeze_generation_source(job, version)
    assert frozen["script_sha256"] == script_digest(draft["text"])
    assert frozen["voice"]["sha256"] == sha256(voice)
    assert "writing_origin" not in frozen
    version.writing_origin = {
        **{
            key: str(uuid4())
            for key in (
                "adoption_id",
                "draft_document_id",
                "reference_document_id",
                "analysis_document_id",
                "facts_document_id",
            )
        },
        "draft_document_sha256": "a" * 64,
        "rules_release": "b" * 64,
        "script_sha256": frozen["script_sha256"],
    }
    assert (
        freeze_generation_source(job, version)["writing_origin"]
        == version.writing_origin
    )
    assert (
        matching_writing_origin(
            version.writing_origin,
            {
                "draft": {**draft, "drive": "audio"},
            },
        )
        is None
    )
    with pytest.raises(ApiError) as wrong_scope:
        freeze_generation_source(job, None)
    assert wrong_scope.value.code == "EDITING_GENERATION_SCRIPT_CHANGED"

    job.details["snapshot"]["draft"]["text"] = "另一份确认稿"
    with pytest.raises(ApiError) as wrong_text:
        freeze_generation_source(job, version)
    assert wrong_text.value.code == "EDITING_GENERATION_SCRIPT_CHANGED"

    version.snapshot = {"draft": {"drive": "audio", "text": "旧文本未用于配音"}}
    job.details["snapshot"]["draft"] = {"drive": "audio", "text": ""}
    assert script_reference(version) is None
    with pytest.raises(ApiError) as wrong_origin:
        freeze_generation_source(job, version)
    assert wrong_origin.value.code == "EDITING_GENERATION_SCRIPT_CHANGED"
    version.writing_origin = None
    assert freeze_generation_source(job, version)["script_sha256"] is None


def test_source_receipt_flags_voice_clock_difference_and_detects_changed_bytes(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "voice.mp3"
    path.write_bytes(b"original")
    binding = {"status": "bound", "path": str(path), "sha256": sha256(path)}
    lineage = {"generation_script_snapshot": "matched", "voice": binding}
    embedded = {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio", "start_time": "0.000", "duration": "2.000"},
        ],
        "format": {"duration": "2.000"},
    }
    separate = {
        "streams": [{"codec_type": "audio"}],
        "format": {"start_time": "0.025", "duration": "2.225"},
    }
    monkeypatch.setattr(
        "app.video_editing_source_lineage.probe", lambda *args, **kwargs: separate
    )
    options = (
        {"kind": "generation_task"},
        lineage,
        {"probe": embedded, "audio_sha256": "a" * 64},
        Settings(),
        lambda: None,
    )
    report = generation_source_receipt(*options)
    assert report["separate_voice"]["status"] == "clock_differs"
    assert report["separate_voice"]["delta_from_video_audio_ms"] == {
        "start": 25,
        "duration": 225,
    }
    assert report["selected_audio"] == "original_video_audio"
    assert report["separate_voice_used"] is False
    assert str(path) not in str(report)
    path.write_bytes(b"replacement")
    assert (
        generation_source_receipt(*options)["separate_voice"]["status"]
        == "bytes_changed"
    )


def test_only_wav_clock_uses_its_implicit_zero_start():
    base = {"streams": [{"codec_type": "audio"}]}
    assert (
        audio_clock({**base, "format": {"duration": "2", "format_name": "mp3"}}) is None
    )
    assert audio_clock({**base, "format": {"duration": "2", "format_name": "wav"}}) == {
        "start_ms": 0,
        "duration_ms": 2000,
    }


@pytest.mark.parametrize(
    "container, peak, allowed, inspect_tail",
    [
        (2.02, 0, True, False),
        (2.08, 0, True, True),
        (2.08, 1200, False, True),
        (2.60, 0, False, False),
    ],
)
def test_prepare_excludes_only_a_short_verified_silent_tail(
    tmp_path, monkeypatch, container, peak, allowed, inspect_tail
):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"unchanged-input")
    attempt = tmp_path / "attempt"
    digest = sha256(source)
    calls = []
    monkeypatch.setattr(
        "app.video_editing_pipeline.probe",
        lambda *_: {
            "format": {"duration": str(container)},
            "streams": [
                {"codec_type": "video", "duration": "2.000", "avg_frame_rate": "30/1"},
                {
                    "codec_type": "audio",
                    "start_time": "0.010",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        },
    )

    def run(argv, root, settings, guard, name):
        calls.append(name)
        output = Path(argv[-1])
        if name == "inspect_audio_tail":
            assert (
                "-ac" not in argv
                and "atrim=start=1.990000" in argv[argv.index("-af") + 1]
            )
            output.write_bytes(pack("<hh", peak, -peak) * 4000)
        else:
            with open_wave(str(output), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(bytes(32000 * 2 + 2560))
        return output

    monkeypatch.setattr("app.video_editing_pipeline.run", run)
    if allowed:
        report = prepare(source, digest, attempt, Settings(), lambda: None)
        assert report["source_sha256"] == digest
        assert report["duration_ms"] == (2000 if inspect_tail else 2020)
        assert report["clock"]["analysis_audio_end_ms"] == 2090
        tail = report["clock"].get("silent_tail")
        if inspect_tail:
            assert tail == {
                "container_end_ms": 2080,
                "video_end_ms": 2000,
                "audio_tail_frames": 4000,
                "sample_rate": 48000,
                "channels": 2,
                "pcm16_peak": 0,
                "analysis_audio_end_ms": 2090,
            }
        else:
            assert tail is None
    else:
        with pytest.raises(
            EditingFailure, match="EDITING_SOURCE_AUDIO_TAIL_REVIEW_REQUIRED"
        ):
            prepare(source, digest, attempt, Settings(), lambda: None)
    assert ("inspect_audio_tail" in calls) == inspect_tail
    assert ("extract_audio" in calls) == allowed
    assert sha256(source) == digest == sha256(attempt / "input/source.mp4")
