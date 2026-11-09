"""Verified handoff references and diagnostics are separate from the audio used."""

import pytest

from app.config import Settings
from app.errors import ApiError
from app.motion_library import sha256
from app.video_editing_source_lineage import (
    audio_clock,
    freeze_generation_source,
    generation_source_receipt,
    script_digest,
    script_reference,
)
from app.video_generation_models import VideoGenerationRecord
from app.video_studio_models import VideoScriptVersionRecord


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
