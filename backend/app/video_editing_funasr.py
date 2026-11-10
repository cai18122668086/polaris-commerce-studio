"""Pinned local Mandarin ASR; timestamps come from Paraformer, never word speed.

Uses FunASR's Python API only. No FunClip UI, eval or remote model code is used.
Punctuation is attached to measured words only when the surface units agree.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

from .motion_library import atomic_json, inside, read_json, sha256
from .video_editing_contracts import Transcript, TranscriptToken, TranscriptUtterance
from .video_editing_pipeline import (
    ASR_TIMESTAMP_TOLERANCE_MS,
    EditingFailure,
    reference_differences,
    word_timestamp_end_limit,
)

PROCESSING_VERSION = "funasr-word-clock/2"
# The pinned Paraformer stacks six 10 ms steps and can pad the final frame.
_PARAFORMER_FINAL_FRAME_MS = 60
MANIFEST = Path(__file__).parent / "data/editing_funasr_models.json"
UNIT = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


def bundle_identity(
    root: Path, *, verify: bool = True, manifest_path: Path | None = None
) -> str:
    selected_manifest = manifest_path or MANIFEST
    manifest = read_json(selected_manifest)
    if verify:
        for name, model in manifest["models"].items():
            for item in model["files"]:
                path = inside(root / name, item["Path"])
                if (
                    not path.is_file()
                    or path.stat().st_size != item["Size"]
                    or sha256(path) != item["Sha256"]
                ):
                    raise EditingFailure("EDITING_ASR_MODEL_INTEGRITY_FAILED")
    return sha256(selected_manifest)


def normalize_result(
    result: list[dict[str, Any]],
    prepared: dict,
    model: str,
    identity: str,
    version: str,
    reference: str | None = None,
    *,
    paraformer: bool = True,
) -> Transcript:
    """One raw token ↔ one actual model interval. Fail closed on disagreement."""
    if len(result) != 1 or not result[0].get("timestamp"):
        raise EditingFailure("EDITING_ASR_WORD_TIMESTAMPS_REQUIRED")
    row = result[0]
    raw_units = row.get("raw_text", "").split()
    surface = row.get("text", "")
    matches = list(UNIT.finditer(surface))
    stamps = row["timestamp"]
    if len(raw_units) != len(stamps) or [u.casefold() for u in raw_units] != [
        m.group().casefold() for m in matches
    ]:
        raise EditingFailure("EDITING_ASR_TEXT_TIMESTAMPS_MISMATCH")
    tokens: list[TranscriptToken] = []
    adjustments = []
    offset = prepared["clock"]["audio_offset_ms"]
    duration = prepared["duration_ms"]
    end_limit = word_timestamp_end_limit(prepared)
    sample_end = prepared["clock"].get("analysis_audio_end_ms") if paraformer else None
    anchor_end = duration
    if sample_end is not None:
        anchor_end = min(duration, sample_end)
        end_limit = sample_end + ASR_TIMESTAMP_TOLERANCE_MS
    for i, (unit, stamp, match) in enumerate(
        zip(raw_units, stamps, matches, strict=True)
    ):
        if len(stamp) != 2 or any(type(v) is not int for v in stamp):
            raise EditingFailure("EDITING_ASR_TIMING_INVALID")
        start, end = stamp[0] + offset, stamp[1] + offset
        padded_end = (
            sample_end is not None
            and i == len(stamps) - 1
            and end_limit < end <= sample_end + _PARAFORMER_FINAL_FRAME_MS
        )
        if not (0 <= start < anchor_end and start < end) or (
            end > end_limit and not padded_end
        ):
            raise EditingFailure("EDITING_ASR_TIMING_INVALID")
        if end > anchor_end:
            reason = (
                "clip_verified_silent_tail_to_picture_end"
                if anchor_end == duration and prepared["clock"].get("silent_tail")
                else "clip_model_quantization_to_actual_audio_end"
            )
            if padded_end:
                reason = "clip_paraformer_final_padding_to_media_end"
            adjustments.append(
                {
                    "token_id": f"t{i:06}",
                    "native_end_ms": end,
                    "end_ms": anchor_end,
                    "reason": reason,
                    **({"analysis_audio_end_ms": sample_end} if padded_end else {}),
                }
            )
            end = anchor_end
        if tokens and start < tokens[-1].end_ms:
            raise EditingFailure("EDITING_ASR_TIMING_INVALID")
        suffix = surface[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else None
        ]
        # Spaces/punctuation have no independent duration. Never spread word clocks.
        text = unit + re.sub(r"\s", "", suffix)
        if i == 0:
            text = re.sub(r"\s", "", surface[: match.start()]) + text
        tokens.append(
            TranscriptToken(id=f"t{i:06}", text=text, start_ms=start, end_ms=end)
        )
    if not tokens:
        raise EditingFailure("EDITING_NO_SPEECH_RECOGNIZED")
    utterances: list[TranscriptUtterance] = []
    cursor = 0
    for sentence in row.get("sentence_info", []):
        units = sentence.get("raw_text", "").split()
        count = len(units)
        selected = tokens[cursor : cursor + count]
        if (
            not count
            or units != raw_units[cursor : cursor + count]
            or sentence.get("timestamp") != stamps[cursor : cursor + count]
        ):
            raise EditingFailure("EDITING_ASR_SENTENCES_MISMATCH")
        utterances.append(
            TranscriptUtterance(
                id=f"u{len(utterances):05}",
                text="".join(t.text for t in selected),
                token_ids=[t.id for t in selected],
                start_ms=selected[0].start_ms,
                end_ms=selected[-1].end_ms,
            )
        )
        cursor += count
    if cursor != len(tokens):
        raise EditingFailure("EDITING_ASR_SENTENCES_MISMATCH")
    spoken = "".join(t.text for t in tokens)
    matches_reference, differences = reference_differences(spoken, reference)
    return Transcript(
        audio_sha256=prepared["audio_sha256"],
        source_sha256=prepared["source_sha256"],
        duration_ms=duration,
        provider="funasr",
        model=model,
        model_sha256=identity,
        recognizer_version=version,
        processing_version=PROCESSING_VERSION,
        raw_result_sha256=hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        language="zh",
        tokens=tokens,
        utterances=utterances,
        reference_text=reference,
        reference_matches=matches_reference,
        differences=differences,
        warnings=["自动识别和标点仍需校对；词点精度与语义尚未人工验收。"],
        timing_adjustments=adjustments,
    )


def transcribe_funasr(
    audio: Path, prepared: dict, model_root: Path, device: str, reference: str | None
) -> Transcript:
    # Paths are the operator's pinned local bundle, never supplied by an LLM.
    identity = bundle_identity(model_root)
    from funasr import AutoModel

    model = AutoModel(
        model=str(model_root / "paraformer"),
        vad_model=str(model_root / "vad"),
        punc_model=str(model_root / "punc"),
        device=device,
        ncpu=4,
        disable_update=True,
        trust_remote_code=False,
    )
    result = model.generate(
        input=str(audio),
        sentence_timestamp=True,
        return_raw_text=True,
        pred_timestamp=True,
        batch_size_s=60,
    )
    atomic_json(audio.parent.parent / "asr-raw.json", result)
    return normalize_result(
        result,
        prepared,
        str(model_root),
        identity,
        importlib.metadata.version("funasr"),
        reference,
    )
