"""Default generated narration: confirmed script + embedded audio's native FA clock."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .motion_library import atomic_json, read_json, sha256
from .video_editing_alignment import ALIGNMENT_MANIFEST, measured_alignment
from .video_editing_contracts import Transcript
from .video_editing_funasr import bundle_identity
from .video_editing_pipeline import EditingFailure, run
from .video_writing_provenance import script_digest

VERSION = "confirmed-script-force-align/1"
EVIDENCE = (
    "confirmed-script.json",
    "alignment-input.txt",
    "alignment-raw.json",
    "alignment-receipt.json",
)


def confirmed_input(snapshot: dict[str, Any], prepared: dict) -> dict | None:
    """An optional reference field cannot impersonate a generation confirmation."""
    origin = snapshot.get("source_origin") or {}
    text = snapshot.get("reference")
    if origin.get("kind") != "generation_task" or not text:
        return None  # Uploaded/video-audio-driven sources retain recognition.
    lineage = snapshot.get("generation_lineage") or {}
    if (
        not snapshot.get("confirmed_version_valid")
        or not origin.get("confirmed_version_id")
        or not origin.get("generation_task_id")
        or lineage.get("generation_script_snapshot") != "matched"
        or script_digest(text) != lineage.get("script_sha256")
        or origin.get("script_sha256") != script_digest(text)
        or origin.get("media_sha256") != prepared["source_sha256"]
    ):
        raise EditingFailure("EDITING_GENERATION_SCRIPT_CHANGED")
    if snapshot["options"].get("language", "zh") not in {"zh", "auto"}:
        raise EditingFailure("EDITING_ALIGNMENT_LANGUAGE_UNSUPPORTED")
    return {
        "schema": "tengli.confirmed-script-alignment-input/1",
        "policy": VERSION,
        "text": text,
        "script_sha256": script_digest(text),
        "source_origin": origin,
        "source_sha256": prepared["source_sha256"],
        "audio_sha256": prepared["audio_sha256"],
        "duration_ms": prepared["duration_ms"],
        "audio_source": "original_video_audio",
    }


def normalize_confirmed(
    result: list[dict[str, Any]],
    binding: dict,
    prepared: dict,
    model_root: Path,
    identity: str,
    version: str,
) -> Transcript:
    if (
        binding["source_sha256"] != prepared["source_sha256"]
        or binding["audio_sha256"] != prepared["audio_sha256"]
        or binding["duration_ms"] != prepared["duration_ms"]
        or script_digest(binding["text"]) != binding["script_sha256"]
    ):
        raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
    transcript = measured_alignment(
        result,
        binding["text"],
        prepared,
        model_root,
        identity,
        version,
        binding["text"],
    )
    data = transcript.model_dump()
    prefix = hashlib.sha256(
        json.dumps(
            [binding, identity, version, VERSION],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:12]
    rename = {t.id: f"f{prefix}-{t.id}" for t in transcript.tokens}
    for token in data["tokens"]:
        token["id"] = rename[token["id"]]
    for utterance in data["utterances"]:
        utterance["id"] = f"f{prefix}-{utterance['id']}"
        utterance["token_ids"] = [rename[t] for t in utterance["token_ids"]]
    for adjustment in data["timing_adjustments"]:
        adjustment["token_id"] = rename[adjustment["token_id"]]
    data.update(
        provider="funasr-fa-zh",
        processing_version=VERSION,
        raw_result_sha256=hashlib.sha256(
            json.dumps(
                result,
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        confirmed_alignment={
            "status": "aligned",
            "policy": VERSION,
            "script_sha256": binding["script_sha256"],
            "source_origin": binding["source_origin"],
            "audio_sha256": binding["audio_sha256"],
            "audio_source": "original_video_audio",
            "timing_source": "native_forced_alignment_intervals",
        },
        warnings=[
            "字幕正文来自该口播任务绑定的确认稿，词点由成片实际音轨强制对齐。",
            "强制对齐不独立证明每个字均被说出，词点仍可试听核对。",
        ],
    )
    return Transcript.model_validate(data)


def align_confirmed(root: Path, config: dict) -> Transcript:
    if not sys.flags.utf8_mode:
        raise EditingFailure("EDITING_ALIGNMENT_UTF8_REQUIRED")
    prepared = read_json(root / "prepared.json")
    audio = root / "input/speech.wav"
    if not audio.is_file() or sha256(audio) != prepared["audio_sha256"]:
        raise EditingFailure("EDITING_ALIGNMENT_AUDIO_CHANGED")
    model_root = Path(config["model"])
    if root.resolve().is_relative_to(model_root.resolve()):
        raise ValueError("Alignment output must remain outside the model bundle")
    if any((root / name).exists() for name in (*EVIDENCE, "transcript.json")):
        raise FileExistsError("Preserve previous alignment in its own attempt")
    identity = bundle_identity(model_root, manifest_path=ALIGNMENT_MANIFEST)
    binding = config["confirmed_script"]
    atomic_json(root / "confirmed-script.json", binding)
    text_file = root / "alignment-input.txt"
    text_file.write_text(binding["text"], encoding="utf-8")
    from funasr import AutoModel

    model = AutoModel(
        model=str(model_root / "fa_zh"),
        device=config["device"],
        ncpu=4,
        disable_update=True,
        trust_remote_code=False,
    )
    result = model.generate(
        input=(str(audio), str(text_file)),
        data_type=("sound", "text"),
        batch_size=1,
    )
    atomic_json(root / "alignment-raw.json", result)
    transcript = normalize_confirmed(
        result,
        binding,
        prepared,
        model_root,
        identity,
        importlib.metadata.version("funasr"),
    )
    atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
    atomic_json(
        root / "alignment-receipt.json",
        {
            "processing_version": VERSION,
            "source_sha256": prepared["source_sha256"],
            "audio_sha256": prepared["audio_sha256"],
            "confirmed_script_sha256": sha256(root / "confirmed-script.json"),
            "input_text_sha256": sha256(text_file),
            "model_bundle_sha256": identity,
            "raw_file_sha256": sha256(root / "alignment-raw.json"),
            "transcript_sha256": sha256(root / "transcript.json"),
            "tokens": len(transcript.tokens),
            "recognition_calls": 0,
            "alignment_calls": 1,
            "timing_review": "unreviewed",
        },
    )
    return transcript


def load_confirmed(
    task_id: str,
    root: Path,
    prepared: dict,
    snapshot: dict[str, Any],
    binding: dict,
    settings: Settings,
    guard: Callable[..., None],
    stage: Callable[..., None],
) -> Transcript:
    if not settings.video_editing_alignment_enabled:
        raise EditingFailure("EDITING_ALIGNMENT_DISABLED")
    stage("aligning")
    model = settings.video_editing_alignment_model_dir
    identity = bundle_identity(model, manifest_path=ALIGNMENT_MANIFEST)
    profile = hashlib.sha256(
        json.dumps(
            {
                "binding": binding,
                "model_identity": identity,
                "funasr_version": importlib.metadata.version("funasr"),
                "device": settings.video_editing_asr_device,
                "processing": VERSION,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    cached = snapshot["checkpoint"].get("transcript") or {}
    path = Path(cached.get("path", ""))
    evidence = cached.get("confirmed_alignment_evidence", {})
    transcript = None
    task_root = (settings.video_editing_tasks_dir / task_id).resolve()
    if (
        cached.get("profile") == profile
        and path.resolve().is_relative_to(task_root)
        and path.is_file()
        and sha256(path) == cached.get("sha256")
        and set(evidence) == set(EVIDENCE)
        and all(
            Path(item["path"]).resolve().is_relative_to(task_root)
            and Path(item["path"]).is_file()
            and sha256(Path(item["path"])) == item["sha256"]
            for item in evidence.values()
        )
        and read_json(Path(evidence["confirmed-script.json"]["path"])) == binding
    ):
        transcript = Transcript.model_validate(read_json(path))
        for name, item in evidence.items():
            shutil.copyfile(item["path"], root / name)
        shutil.copyfile(path, root / "transcript.json")
    if transcript is None:
        atomic_json(
            root / "alignment-config.json",
            {
                "model": str(model),
                "device": settings.video_editing_asr_device,
                "confirmed_script": binding,
            },
        )
        run(
            [
                settings.video_editing_python,
                "-B",
                "-X",
                "utf8",
                "-m",
                "app.video_editing_confirmed_alignment",
                "--instance",
                str(root),
            ],
            root,
            settings,
            guard,
            "alignment",
        )
        transcript = Transcript.model_validate(read_json(root / "transcript.json"))
    if (
        transcript.provider != "funasr-fa-zh"
        or transcript.model != str(model)
        or transcript.model_sha256 != identity
        or transcript.source_sha256 != prepared["source_sha256"]
        or transcript.audio_sha256 != prepared["audio_sha256"]
        or transcript.duration_ms != prepared["duration_ms"]
        or transcript.processing_version != VERSION
        or transcript.text_revision_id is not None
        or transcript.parent_transcript_sha256 is not None
        or transcript.text_status != "automatic"
        or "".join(t.text for t in transcript.tokens) != binding["text"]
    ):
        raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
    stage(
        "storing" if snapshot["options"].get("mode") == "transcript" else "compiling",
        transcript={
            "path": str(root / "transcript.json"),
            "sha256": sha256(root / "transcript.json"),
            "profile": profile,
            "confirmed_alignment_evidence": {
                name: {"path": str(root / name), "sha256": sha256(root / name)}
                for name in EVIDENCE
            },
        },
    )
    return transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    root = parser.parse_args().instance.resolve()
    align_confirmed(root, read_json(root / "alignment-config.json"))


if __name__ == "__main__":
    main()
