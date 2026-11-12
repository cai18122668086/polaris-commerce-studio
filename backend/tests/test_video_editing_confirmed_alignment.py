from copy import deepcopy
from pathlib import Path

import pytest

from app.config import Settings
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_confirmed_alignment import (
    VERSION,
    confirmed_input,
    normalize_confirmed,
)
from app.video_editing_contracts import Transcript
from app.video_editing_pipeline import EditingFailure
from app.video_editing_reference_text import caption_boundaries
from app.video_editing_worker import load_transcript
from app.video_writing_provenance import script_digest


def fixture():
    prepared = {
        "source_sha256": "b" * 64,
        "audio_sha256": "a" * 64,
        "duration_ms": 2000,
        "clock": {"audio_offset_ms": 0},
    }
    text = "洗碗，逐张核对。"
    snapshot = {
        "reference": text,
        "confirmed_version_valid": True,
        "source_origin": {
            "kind": "generation_task",
            "confirmed_version_id": "version-one",
            "generation_task_id": "generation-one",
            "script_sha256": script_digest(text),
            "media_sha256": "b" * 64,
        },
        "generation_lineage": {
            "script_sha256": script_digest(text),
            "generation_script_snapshot": "matched",
        },
        "options": {"language": "zh", "mode": "transcript"},
        "correction": None,
        "checkpoint": {},
    }
    result = [
        {
            "text": "洗 碗 逐 张 核 对",
            "timestamp": [
                [110, 200],
                [240, 390],
                [600, 790],
                [820, 950],
                [1000, 1200],
                [1300, 1450],
            ],
        }
    ]
    return snapshot, prepared, result


def test_default_uses_immutable_confirmation_and_real_intervals_without_asr_parent():
    snapshot, prepared, result = fixture()
    snapshot["options"]["reference_script"] = "用户临时填的另一稿"
    binding = confirmed_input(snapshot, prepared)
    assert binding["text"] == snapshot["reference"]
    transcript = normalize_confirmed(
        result, binding, prepared, Path("model"), "c" * 64, "1"
    )
    assert "".join(t.text for t in transcript.tokens) == snapshot["reference"]
    assert [[t.start_ms, t.end_ms] for t in transcript.tokens] == result[0]["timestamp"]
    assert transcript.provider == "funasr-fa-zh"
    assert transcript.text_status == "automatic"
    assert transcript.processing_version == VERSION
    assert transcript.text_revision_id is None
    assert transcript.parent_transcript_sha256 is None
    assert transcript.reference_reconciliation == {}
    assert transcript.confirmed_alignment["audio_source"] == "original_video_audio"
    boundaries = caption_boundaries(transcript)
    assert boundaries["cue_end_token_ids"] == [transcript.tokens[i].id for i in (1, 5)]
    assert boundaries["sentence_end_token_ids"] == [transcript.tokens[-1].id]


@pytest.mark.parametrize(
    "change", ["version", "media", "script", "lineage", "language"]
)
def test_invalid_generation_provenance_never_silently_falls_back_to_asr(change):
    snapshot, prepared, _ = fixture()
    if change == "version":
        snapshot["confirmed_version_valid"] = False
    if change == "media":
        snapshot["source_origin"]["media_sha256"] = "0" * 64
    if change == "script":
        snapshot["reference"] += "额外的话。"
    if change == "lineage":
        snapshot["generation_lineage"]["generation_script_snapshot"] = "not_recorded"
    if change == "language":
        snapshot["options"]["language"] = "en"
    with pytest.raises(EditingFailure):
        confirmed_input(snapshot, prepared)


def test_uploaded_reference_and_audio_driven_generation_keep_recognition():
    snapshot, prepared, _ = fixture()
    snapshot["source_origin"]["kind"] = "upload_asset"
    assert confirmed_input(snapshot, prepared) is None
    snapshot["source_origin"]["kind"] = "generation_task"
    snapshot["reference"] = None
    assert confirmed_input(snapshot, prepared) is None


def test_missing_or_invented_native_clocks_cannot_be_replaced_by_equal_time():
    snapshot, prepared, result = fixture()
    binding = confirmed_input(snapshot, prepared)
    for invalid in (
        [{"text": "洗 碗 逐 张 核 对"}],
        [{"text": "洗碗 逐 张 核 对", "timestamp": result[0]["timestamp"]}],
    ):
        with pytest.raises(EditingFailure):
            normalize_confirmed(
                invalid, binding, prepared, Path("model"), "c" * 64, "1"
            )
    changed = deepcopy(binding)
    changed["audio_sha256"] = "0" * 64
    with pytest.raises(EditingFailure):
        normalize_confirmed(result, changed, prepared, Path("model"), "c" * 64, "1")


def test_worker_default_and_recovery_require_complete_hashed_fa_evidence(
    tmp_path, monkeypatch
):
    import app.video_editing_confirmed_alignment as module

    snapshot, prepared, result = fixture()
    settings = Settings(
        _env_file=None,
        video_editing_alignment_enabled=True,
        video_editing_tasks_dir=tmp_path,
        video_editing_alignment_model_dir=Path("model"),
    )
    monkeypatch.setattr(module, "bundle_identity", lambda *a, **k: "c" * 64)
    installed_version = module.importlib.metadata.version
    monkeypatch.setattr(
        module.importlib.metadata,
        "version",
        lambda name: "1" if name == "funasr" else installed_version(name),
    )
    calls = []
    stages = []

    def stage(name, **values):
        stages.append(name)
        snapshot["checkpoint"].update(values)

    def actual_fa_subprocess(command, root, *_):
        calls.append(command)
        config = read_json(root / "alignment-config.json")
        binding = config["confirmed_script"]
        transcript = normalize_confirmed(
            result, binding, prepared, Path("model"), "c" * 64, "1"
        )
        atomic_json(root / "confirmed-script.json", binding)
        (root / "alignment-input.txt").write_text(binding["text"], encoding="utf8")
        atomic_json(root / "alignment-raw.json", result)
        atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
        atomic_json(
            root / "alignment-receipt.json",
            {"transcript_sha256": sha256(root / "transcript.json")},
        )

    monkeypatch.setattr(module, "run", actual_fa_subprocess)
    for attempt in ("first", "recovered"):
        root = tmp_path / "task" / attempt
        root.mkdir(parents=True)
        assert isinstance(
            load_transcript(
                "task", root, prepared, snapshot, settings, lambda: None, stage
            ),
            Transcript,
        )
    assert len(calls) == 1 and "app.video_editing_confirmed_alignment" in calls[0]
    assert "transcribing" not in stages
    saved = snapshot["checkpoint"]["transcript"]["confirmed_alignment_evidence"]
    Path(saved["alignment-raw.json"]["path"]).write_text("tampered", encoding="utf8")
    root = tmp_path / "task" / "changed-evidence"
    root.mkdir()
    load_transcript("task", root, prepared, snapshot, settings, lambda: None, stage)
    assert len(calls) == 2  # A valid cached transcript alone is insufficient.


def test_disabled_fa_does_not_present_recognition_as_forced_alignment(tmp_path):
    snapshot, prepared, _ = fixture()
    settings = Settings(_env_file=None, video_editing_alignment_enabled=False)
    with pytest.raises(EditingFailure, match="EDITING_ALIGNMENT_DISABLED"):
        load_transcript(
            "task",
            tmp_path,
            prepared,
            snapshot,
            settings,
            lambda: None,
            lambda *a, **k: None,
        )
