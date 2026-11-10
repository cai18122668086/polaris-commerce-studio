"""Score a frozen Mandarin word clock against separately marked source audio."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import wave
from itertools import accumulate
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.motion_library import read_json, sha256
from app.video_editing_contracts import Transcript

_READABLE = re.compile(r"[^\W_]|(?<=\d)[,.，](?=\d)|[%±+−-]")
_LIMITS_MS = {"word": 150, "utterance": 300}


class Mark(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["word", "utterance"]
    text: str = Field(min_length=1, max_length=500)
    occurrence: int = Field(ge=1)
    occurrences: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_boundaries(self) -> Self:
        if (
            not _READABLE.search(self.text)
            or self.occurrence > self.occurrences
            or (self.kind == "word" and self.end_ms is not None)
            or (
                self.kind == "utterance"
                and (self.end_ms is None or self.end_ms <= self.start_ms)
            )
        ):
            raise ValueError("Invalid reference occurrence or boundary")
        return self


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["tengli.motion-timing-reference/1"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    timebase: Literal["analysis_wav_ms"]
    origin: Literal["human", "diagnostic"]
    marks: list[Mark] = Field(min_length=1)


def _readable(text: str) -> str:
    return "".join(match.group() for match in _READABLE.finditer(text))


def score(
    transcript: Transcript, reference: Reference, offset_ms: int, audio_end_ms: int
) -> dict:
    if (reference.source_sha256, reference.audio_sha256) != (
        transcript.source_sha256,
        transcript.audio_sha256,
    ):
        raise ValueError("Reference and transcript must describe the same recording")

    parts = [token.text.casefold() for token in transcript.tokens]
    raw_offsets = list(accumulate(map(len, parts), initial=0))
    raw = "".join(parts)
    letters = list(_READABLE.finditer(raw))
    spoken = "".join(match.group() for match in letters)
    # Canonical character positions map to whole measured token boundaries.
    # Do not derive character timing from inside a recognizer token.
    starts, ends = {}, {}
    cursor = 0
    for i, boundary in enumerate(raw_offsets[1:]):
        first_char = cursor
        while cursor < len(letters) and letters[cursor].start() < boundary:
            cursor += 1
        if first_char != cursor:
            starts[first_char] = i
            ends[cursor] = i
    utterances = {
        (u.token_ids[0], u.token_ids[-1]): u.id for u in transcript.utterances
    }

    seen = set()
    rows = []
    wav_duration_ms = audio_end_ms - offset_ms
    for mark in reference.marks:
        needle = _readable(mark.text.casefold())
        key = (mark.kind, needle, mark.occurrence)
        if (
            key in seen
            or mark.start_ms >= wav_duration_ms
            or (mark.end_ms is not None and mark.end_ms > wav_duration_ms)
        ):
            raise ValueError("Duplicate reference mark or mark beyond the WAV")
        seen.add(key)
        candidates = list(re.finditer(r"(?=" + re.escape(needle) + r")", spoken))
        limit = _LIMITS_MS[mark.kind]
        row = {
            **mark.model_dump(exclude_none=True),
            "observed_occurrences": len(candidates),
            "tolerance_ms": limit,
        }
        rows.append(row)
        if len(candidates) != mark.occurrences:
            row["result"] = "occurrence_count_mismatch"
            continue
        begin = candidates[mark.occurrence - 1].start()
        end = begin + len(needle)
        if begin not in starts or end not in ends:
            row["result"] = "inside_measured_token"
            continue
        first, last = transcript.tokens[starts[begin]], transcript.tokens[ends[end]]
        row["first_token_id"], row["last_token_id"] = first.id, last.id
        if mark.kind == "utterance":
            utterance_id = utterances.get((first.id, last.id))
            if utterance_id is None:
                row["result"] = "utterance_boundary_mismatch"
                continue
            row["utterance_id"] = utterance_id
        start_error = first.start_ms - (mark.start_ms + offset_ms)
        row["measured_start_wav_ms"] = first.start_ms - offset_ms
        row["start_error_ms"] = start_error
        errors = [abs(start_error)]
        if mark.end_ms is not None:
            end_error = last.end_ms - (mark.end_ms + offset_ms)
            row["measured_end_wav_ms"] = last.end_ms - offset_ms
            row["end_error_ms"] = end_error
            errors.append(abs(end_error))
        row["result"] = (
            "within_tolerance" if max(errors) <= limit else "out_of_tolerance"
        )

    summary = {}
    for kind in _LIMITS_MS:
        selected = [row for row in rows if row["kind"] == kind]
        measured = [row for row in selected if "start_error_ms" in row]
        summary[kind] = {
            "labels": len(selected),
            "measured": len(measured),
            "within_tolerance": sum(
                row["result"] == "within_tolerance" for row in selected
            ),
            "max_absolute_error_ms": max(
                (
                    abs(row[edge])
                    for row in measured
                    for edge in ("start_error_ms", "end_error_ms")
                    if edge in row
                ),
                default=None,
            ),
        }
    if any(row["result"] != "within_tolerance" for row in rows):
        status = "sample_failed"
    elif all(item["labels"] for item in summary.values()):
        status = "sample_within_tolerance"
    else:
        status = "sample_incomplete"
    return {
        "status": status,
        "origin": reference.origin,
        "scope": "marked_audio_sample",
        "summary": summary,
        "marks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "audio", "transcript", "reference", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepared = read_json(args.prepared)
        clock = prepared["clock"]
        offset = clock["audio_offset_ms"]
        audio_end = clock["analysis_audio_end_ms"]
        transcript_data = args.transcript.read_bytes()
        reference_data = args.reference.read_bytes()
        transcript = Transcript.model_validate_json(transcript_data)
        reference = Reference.model_validate_json(reference_data)
        if (
            transcript.source_sha256 != prepared["source_sha256"]
            or transcript.audio_sha256 != prepared["audio_sha256"]
            or transcript.audio_sha256 != sha256(args.audio)
            or transcript.duration_ms != prepared["duration_ms"]
            or type(offset) is not int
            or type(audio_end) is not int
            or audio_end <= offset
        ):
            raise ValueError("Prepared media, WAV and frozen transcript disagree")
        with wave.open(str(args.audio), "rb") as audio:
            measured_end = round(
                audio.getnframes() * 1000 / audio.getframerate() + offset
            )
        if measured_end != audio_end:
            raise ValueError("Prepared media and WAV end clocks disagree")
        report = score(transcript, reference, offset, audio_end)
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(
                {
                    "schema_version": "tengli.motion-timing-report/1",
                    "source_sha256": transcript.source_sha256,
                    "audio_sha256": transcript.audio_sha256,
                    "analysis_audio_offset_ms": offset,
                    "transcript_sha256": hashlib.sha256(transcript_data).hexdigest(),
                    "reference_sha256": hashlib.sha256(reference_data).hexdigest(),
                    "provider": transcript.provider,
                    "processing_version": transcript.processing_version,
                    **report,
                },
                output,
                ensure_ascii=False,
                indent=2,
            )
            output.write("\n")
    except (EOFError, KeyError, OSError, TypeError, ValueError, wave.Error) as error:
        parser.exit(2, f"Timing audit input error: {error}\n")
    print(report["status"])
    if report["status"] != "sample_within_tolerance":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
