"""Real local Chinese forced alignment, preserving the immutable ASR evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

from .motion_library import atomic_json, read_json, sha256
from .video_editing_contracts import Transcript
from .video_editing_funasr import MANIFEST, UNIT, bundle_identity, normalize_result
from .video_editing_pipeline import EditingFailure

ALIGNMENT_MANIFEST = MANIFEST.with_name("editing_alignment_models.json")
PROCESSING_VERSION = "funasr-force-align/1"


def normalize_alignment(
    result: list[dict[str, Any]],
    text: str,
    prepared: dict,
    parent: Transcript,
    parent_sha256: str,
    revision_id: str,
    text_status: Literal["user_corrected", "operator_candidate"],
    model_root: Path,
    model_identity: str,
    version: str,
) -> Transcript:
    """Native token ↔ native interval ↔ supplied text; no equal-time repair."""
    if (
        parent.source_sha256 != prepared["source_sha256"]
        or parent.audio_sha256 != prepared["audio_sha256"]
        or parent.duration_ms != prepared["duration_ms"]
    ):
        raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
    if not revision_id or not text.strip() or len(text) > 20000:
        raise EditingFailure("EDITING_ALIGNMENT_TEXT_REQUIRED")
    if parent.language != "zh":
        raise EditingFailure("EDITING_ALIGNMENT_LANGUAGE_UNSUPPORTED")
    if len(result) != 1 or not result[0].get("timestamp"):
        raise EditingFailure("EDITING_ALIGNMENT_TIMESTAMPS_REQUIRED")
    native_words = result[0].get("text", "").split()
    matches = list(UNIT.finditer(text))
    display_words = [m.group() for m in matches]
    native_stamps = result[0]["timestamp"]
    if len(native_stamps) != len(native_words) or any(
        not isinstance(s, list)
        or len(s) != 2
        or any(type(v) is not int for v in s)
        or not 0 <= s[0] < s[1]
        for s in native_stamps
    ):
        raise EditingFailure("EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH")
    if any(a[1] > b[0] for a, b in zip(native_stamps, native_stamps[1:], strict=False)):
        raise EditingFailure("EDITING_ASR_TIMING_INVALID")
    # Native ASCII digits can be separate tokens. Join only exact consecutive
    # native subtokens, retaining their measured outer bounds. Never split a
    # native interval or distribute its duration among characters.
    stamps = []
    token_map = []
    cursor = 0
    for i, word in enumerate(display_words):
        begin = cursor
        joined = ""
        while joined.casefold() != word.casefold():
            if cursor >= len(native_words):
                raise EditingFailure("EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH")
            joined += native_words[cursor]
            cursor += 1
            if not word.casefold().startswith(joined.casefold()):
                raise EditingFailure("EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH")
        stamps.append([native_stamps[begin][0], native_stamps[cursor - 1][1]])
        if cursor - begin > 1:
            token_map.append(
                {
                    "token_id": f"t{i:06}",
                    "native_token_indices": list(range(begin, cursor)),
                    "native_intervals_ms": native_stamps[begin:cursor],
                    "reason": "join_native_subtokens_preserve_measured_outer_bounds",
                }
            )
    if cursor != len(native_words):
        raise EditingFailure("EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH")
    # Sentence boundaries use only supplied punctuation and actual word bounds.
    # No punctuation model rewrites the user's correction during alignment.
    sentences = []
    begin = 0
    for i, match in enumerate(matches):
        tail = text[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else None
        ]
        if re.search(r"[。！？!?；;\n]", tail) or i == len(matches) - 1:
            sentences.append(
                {
                    "raw_text": " ".join(display_words[begin : i + 1]),
                    "timestamp": stamps[begin : i + 1],
                }
            )
            begin = i + 1
    adapted = [
        {
            "text": text,
            "raw_text": " ".join(display_words),
            "timestamp": stamps,
            "sentence_info": sentences,
        }
    ]
    transcript = normalize_result(
        adapted,
        prepared,
        str(model_root),
        model_identity,
        version,
        parent.reference_text,
    )
    data = transcript.model_dump()
    data["timing_adjustments"].extend(token_map)
    prefix = hashlib.sha256(
        json.dumps(
            [
                revision_id,
                text,
                parent_sha256,
                model_identity,
                version,
                PROCESSING_VERSION,
            ],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:12]
    rename = {t.id: f"a{prefix}-{t.id}" for t in transcript.tokens}
    for token in data["tokens"]:
        token["id"] = rename[token["id"]]
    for utterance in data["utterances"]:
        utterance["id"] = f"a{prefix}-{utterance['id']}"
        utterance["token_ids"] = [rename[t] for t in utterance["token_ids"]]
    for adjustment in data["timing_adjustments"]:
        adjustment["token_id"] = rename[adjustment["token_id"]]
    data.update(
        provider="funasr-fa-zh",
        processing_version=PROCESSING_VERSION,
        raw_result_sha256=hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        parent_transcript_sha256=parent_sha256,
        text_revision_id=revision_id,
        text_status=text_status,
        timing_review="unreviewed",
        warnings=[
            "本时间轴由实际音频与单独保存的文字重新对齐；未人工验证词点精度。",
            "强制对齐不证明文字确实被说出，也不核验商品事实。",
            *(
                ["这是操作者候选文字，尚未经用户校对确认。"]
                if text_status == "operator_candidate"
                else []
            ),
        ],
    )
    return Transcript.model_validate(data)


def align_transcript(
    audio: Path,
    prepared: dict,
    parent: Transcript,
    parent_sha256: str,
    text: str,
    revision_id: str,
    text_status: Literal["user_corrected", "operator_candidate"],
    model_root: Path,
    output: Path,
    device: str = "cpu",
) -> Transcript:
    if not sys.flags.utf8_mode:
        raise EditingFailure("EDITING_ALIGNMENT_UTF8_REQUIRED")
    if not audio.is_file() or sha256(audio) != prepared["audio_sha256"]:
        raise EditingFailure("EDITING_ALIGNMENT_AUDIO_CHANGED")
    if (
        parent.source_sha256 != prepared["source_sha256"]
        or parent.audio_sha256 != prepared["audio_sha256"]
        or parent.duration_ms != prepared["duration_ms"]
    ):
        raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
    if not revision_id or not text.strip() or len(text) > 20000:
        raise EditingFailure("EDITING_ALIGNMENT_TEXT_REQUIRED")
    if output.resolve().is_relative_to(model_root.resolve()):
        raise ValueError(
            "Alignment outputs must remain outside the pinned model bundle"
        )
    if any(
        (output / name).exists()
        for name in ("alignment-input.txt", "alignment-raw.json", "transcript.json")
    ):
        raise FileExistsError(
            "Preserve previous alignment; choose a new revision output"
        )
    identity = bundle_identity(model_root, manifest_path=ALIGNMENT_MANIFEST)
    output.mkdir(parents=True, exist_ok=True)
    text_file = output / "alignment-input.txt"
    text_file.write_text(text, encoding="utf-8")
    from funasr import AutoModel

    model = AutoModel(
        model=str(model_root / "fa_zh"),
        device=device,
        ncpu=4,
        disable_update=True,
        trust_remote_code=False,
    )
    result = model.generate(
        input=(str(audio), str(text_file)),
        data_type=("sound", "text"),
        batch_size=1,
    )
    atomic_json(output / "alignment-raw.json", result)
    transcript = normalize_alignment(
        result,
        text,
        prepared,
        parent,
        parent_sha256,
        revision_id,
        text_status,
        model_root,
        identity,
        importlib.metadata.version("funasr"),
    )
    atomic_json(output / "transcript.json", transcript.model_dump(mode="json"))
    atomic_json(
        output / "alignment-receipt.json",
        {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": prepared["source_sha256"],
            "audio_sha256": prepared["audio_sha256"],
            "parent_transcript_sha256": parent_sha256,
            "text_revision_id": revision_id,
            "text_status": text_status,
            "input_text_sha256": sha256(text_file),
            "model_bundle_sha256": identity,
            "raw_file_sha256": sha256(output / "alignment-raw.json"),
            "transcript_sha256": sha256(output / "transcript.json"),
            "tokens": len(transcript.tokens),
            "timing_review": "unreviewed",
            "semantic_review": "unreviewed",
            "visual_review": "unreviewed",
            "hearing_review": "unreviewed",
        },
    )
    return transcript


def main() -> None:
    """Fixed worker protocol, in a cancellable credential-free subprocess."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    args = parser.parse_args()
    root = args.instance.resolve()
    config = read_json(root / "alignment-config.json")
    parent_file = root / "parent-transcript.json"
    if sha256(parent_file) != config["parent_sha256"]:
        raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
    align_transcript(
        root / "input/speech.wav",
        read_json(root / "prepared.json"),
        Transcript.model_validate(read_json(parent_file)),
        config["parent_sha256"],
        config["text"],
        config["revision_id"],
        config["text_status"],
        Path(config["model"]),
        root,
        config["device"],
    )


if __name__ == "__main__":
    main()
