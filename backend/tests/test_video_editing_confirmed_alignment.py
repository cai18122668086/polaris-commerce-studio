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


# --- P0（v3）：口播结果进剪辑时，多行确认稿对齐必失败 -------------------------
# FunASR 把 .txt 文本输入当作 Kaldi「键 文本」清单：只读第一行，第一个空格前
# 被当成键。线上 29 行口播稿只对齐了第一行 18 个字 → TEXT_TIMESTAMPS_MISMATCH。

MULTILINE = "\n".join(
    f"第{'一二三四五六七八九十'[i % 10]}条，iPhone 15 Pro 的主图要清楚。" for i in range(24)
) + "\n"


def test_multiline_script_reaches_fa_as_one_literal_document(tmp_path, monkeypatch):
    import sys
    import types

    import app.video_editing_confirmed_alignment as module

    root = tmp_path / "attempt"
    (root / "input").mkdir(parents=True)
    audio = root / "input" / "speech.wav"
    audio.write_bytes(b"RIFF-not-really-audio")
    prepared = {
        "source_sha256": "b" * 64,
        "audio_sha256": sha256(audio),
        "duration_ms": 600_000,
        "clock": {"audio_offset_ms": 0},
    }
    atomic_json(root / "prepared.json", prepared)
    seen = {}

    class FakeModel:
        def __init__(self, **_):
            pass

        def generate(self, input, data_type, batch_size):
            path = Path(input[1])
            seen["suffix"] = path.suffix
            seen["text"] = path.read_text(encoding="utf-8")
            # Literal document: every character unit gets one native interval.
            from app.video_editing_funasr import UNIT

            words = [m.group() for m in UNIT.finditer(seen["text"])]
            stamps = [[i * 100 + 10, i * 100 + 90] for i in range(len(words))]
            return [{"text": " ".join(words), "timestamp": stamps}]

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeModel))
    monkeypatch.setattr(module, "sys", types.SimpleNamespace(flags=types.SimpleNamespace(utf8_mode=1)))
    monkeypatch.setattr(module, "bundle_identity", lambda *a, **k: "c" * 64)
    installed_version = module.importlib.metadata.version
    monkeypatch.setattr(
        module.importlib.metadata,
        "version",
        lambda name: "1" if name == "funasr" else installed_version(name),
    )
    binding = {
        "text": MULTILINE,
        "script_sha256": script_digest(MULTILINE),
        "source_origin": {"kind": "generation_task"},
        "source_sha256": prepared["source_sha256"],
        "audio_sha256": prepared["audio_sha256"],
        "duration_ms": prepared["duration_ms"],
    }
    transcript = module.align_confirmed(
        root, {"model": str(tmp_path / "model"), "device": "cpu", "confirmed_script": binding}
    )
    assert seen["suffix"] != ".txt"  # never the key/value manifest loader
    assert seen["text"] == MULTILINE  # all 24 lines, newlines and spaces intact
    assert (root / "alignment-input.txt").read_text(encoding="utf-8") == MULTILINE
    assert "".join(t.text for t in transcript.tokens) == MULTILINE
    assert len(transcript.utterances) >= 24  # line breaks still end captions


def test_subprocess_failure_keeps_its_own_code_for_recognition_steps(tmp_path):
    from app.video_editing_pipeline import subprocess_failure_code

    log = tmp_path / "alignment.log"
    log.write_text(
        "Traceback (most recent call last):\n  File ...\n"
        "app.video_editing_pipeline.EditingFailure: "
        "EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH\n",
        encoding="utf-8",
    )
    assert subprocess_failure_code(log, "alignment") == (
        "EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH"
    )
    assert subprocess_failure_code(log, "asr") is not None
    # Render-like steps keep step codes the UI depends on (e.g. layout failures).
    assert subprocess_failure_code(log, "effect_layout") is None
    assert subprocess_failure_code(tmp_path / "missing.log", "alignment") is None
    log.write_text("killed\n", encoding="utf-8")
    assert subprocess_failure_code(log, "alignment") is None


def test_alignment_mismatch_falls_back_to_recognizing_the_real_speech(
    tmp_path, monkeypatch
):
    import app.video_editing_confirmed_alignment as confirmed
    import app.video_editing_worker as worker

    snapshot, prepared, result = fixture()
    settings = Settings(
        _env_file=None,
        video_editing_alignment_enabled=True,
        video_editing_tasks_dir=tmp_path,
        video_editing_alignment_model_dir=Path("model"),
    )
    monkeypatch.setattr(confirmed, "bundle_identity", lambda *a, **k: "c" * 64)
    installed_version = confirmed.importlib.metadata.version
    monkeypatch.setattr(
        confirmed.importlib.metadata,
        "version",
        lambda name: "1" if name == "funasr" else installed_version(name),
    )
    stages = []

    def stage(name, **values):
        stages.append((name, values))
        snapshot["checkpoint"].update(values)

    def failing_fa(command, root, *_):
        (root / "alignment-input.txt").write_text("partial", encoding="utf8")
        raise EditingFailure("EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH")

    recognized = normalize_confirmed(
        result,
        {
            "text": snapshot["reference"],
            "script_sha256": script_digest(snapshot["reference"]),
            "source_origin": snapshot["source_origin"],
            "source_sha256": prepared["source_sha256"],
            "audio_sha256": prepared["audio_sha256"],
            "duration_ms": prepared["duration_ms"],
        },
        prepared,
        Path("model"),
        "c" * 64,
        "1",
    )
    asr_calls = []

    def asr(command, root, *_):
        asr_calls.append(command)
        config = read_json(root / "asr-config.json")
        assert config["reference"] == snapshot["reference"]  # script still guides recognition
        atomic_json(root / "transcript.json", recognized.model_dump(mode="json"))

    monkeypatch.setattr(confirmed, "run", failing_fa)
    monkeypatch.setattr(worker, "run", asr)
    monkeypatch.setattr(worker, "asr_profile", lambda *a, **k: "p" * 64)
    root = tmp_path / "task" / "attempt"
    root.mkdir(parents=True)
    transcript = load_transcript(
        "task", root, prepared, snapshot, settings, lambda: None, stage
    )
    assert isinstance(transcript, Transcript)
    assert len(asr_calls) == 1 and "app.video_editing_asr" in asr_calls[0]
    names = [name for name, _ in stages]
    assert names[:2] == ["aligning", "transcribing"]
    assert snapshot["checkpoint"]["alignment_fallback"] == {
        "code": "EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH"
    }
    assert (root / "alignment-fallback" / "alignment-input.txt").is_file()
    assert not (root / "alignment-input.txt").exists()


def test_provenance_failures_still_never_fall_back(tmp_path, monkeypatch):
    import app.video_editing_confirmed_alignment as confirmed

    snapshot, prepared, _ = fixture()
    settings = Settings(
        _env_file=None,
        video_editing_alignment_enabled=True,
        video_editing_tasks_dir=tmp_path,
        video_editing_alignment_model_dir=Path("model"),
    )
    monkeypatch.setattr(confirmed, "bundle_identity", lambda *a, **k: "c" * 64)
    installed_version = confirmed.importlib.metadata.version
    monkeypatch.setattr(
        confirmed.importlib.metadata,
        "version",
        lambda name: "1" if name == "funasr" else installed_version(name),
    )

    def audio_changed(*_):
        raise EditingFailure("EDITING_ALIGNMENT_AUDIO_CHANGED")

    monkeypatch.setattr(confirmed, "run", audio_changed)
    with pytest.raises(EditingFailure, match="EDITING_ALIGNMENT_AUDIO_CHANGED"):
        load_transcript(
            "task", tmp_path, prepared, snapshot, settings, lambda: None, lambda *a, **k: None
        )
