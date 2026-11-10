"""Compile allowed native field anchors from measured token occurrences only."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from itertools import accumulate
from typing import Any

from .video_editing_condition_anchors import (
    measured_conditions,
    validate_condition_coverage,
)
from .video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from .video_editing_quantity_anchors import (
    NUMERIC_COLON,
    measured_quantities,
    validate_quantity_slots,
)

_DENIAL_OR_CLAUSE_END = re.compile(
    r"(?P<denial>(?<!是)不是|并非|绝非|不等于|不代表|不意味着|不表示)"
    r"|[。！？；、!?;]|(?<!\d)[.,，]|[.,，](?!\d)|而是"
)


class IncompleteDenial(ValueError):
    code = "EDITING_NEGATION_ANCHOR_INCOMPLETE"


def explicit_denial_spans(tokens: list[TranscriptToken]) -> list[tuple[int, int, int]]:
    """Find explicit denial markers and clause ends in actual token coordinates."""
    text = "".join(token.text for token in tokens)
    offsets = list(accumulate((len(token.text) for token in tokens), initial=0))
    result: list[tuple[int, int, int]] = []
    pending: list[tuple[int, int]] = []
    for match in _DENIAL_OR_CLAUSE_END.finditer(text):
        if match.lastgroup == "denial":
            first = bisect_right(offsets, match.start()) - 1
            last = bisect_right(offsets, match.end() - 1) - 1
            pending.append((first, last))
        elif pending:
            end = bisect_left(offsets, match.start()) - 1
            result.extend((first, last, end) for first, last in pending)
            pending.clear()
    result.extend((first, last, len(tokens) - 1) for first, last in pending)
    return result


def drops_explicit_denial(
    first: int, last: int, denials: list[tuple[int, int, int]]
) -> bool:
    return any(
        marker_first < first <= clause_end
        or first <= marker_first <= last < marker_last
        for marker_first, marker_last, clause_end in denials
    )


def measured_clause_windows(transcript: Transcript) -> Iterator[list[TranscriptToken]]:
    """Yield bounded clause ranges for original template admission hints."""
    tokens = transcript.tokens
    if not tokens:
        return
    cuts = [0]
    cuts.extend(
        index
        for index in range(1, len(tokens))
        if tokens[index - 1].text.rstrip().endswith(tuple("，。！？；、,.!?;"))
        or tokens[index].start_ms - tokens[index - 1].end_ms >= 250
    )
    cuts.append(len(tokens))
    for index, first in enumerate(cuts[:-1]):
        for stop in cuts[index + 1 : index + 4]:
            if tokens[stop - 1].end_ms - tokens[first].start_ms > 6500:
                break
            yield tokens[first:stop]


def emphasis_text(
    text: str, policy: str, *, preserve_numeric_colon: bool = True
) -> str:
    if policy == "preserve":
        return text.strip()
    if policy != "omit_sentence_punctuation":
        raise ValueError("Unknown native punctuation policy")
    # Retain decimal/thousands/ratio punctuation and unit symbols (%, /, ±...).
    colons = (
        {match.start("separator") for match in NUMERIC_COLON.finditer(text)}
        if preserve_numeric_colon
        else set()
    )
    output = []
    for i, char in enumerate(text):
        internal_number = (
            0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
            and char in ".,，:："
        )
        if char not in "，。！？、；：,.!?;:" or internal_number or i in colons:
            output.append(char)
    return "".join(output).strip()


def word_bindings(
    beat: SemanticBeat,
    transcript: Transcript,
    contract: dict[str, Any],
    allowed_assets: set[str],
) -> dict[str, Any]:
    if contract["group_id"] != beat.group_id:
        raise ValueError("Wrong original native input contract")
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    if beat.first_token_id not in positions or beat.last_token_id not in positions:
        raise ValueError("Unknown source occurrence")
    first, last = positions[beat.first_token_id], positions[beat.last_token_id]
    if first > last:
        raise ValueError("Native meaning span is reversed")
    start_ms, end_ms = transcript.tokens[first].start_ms, transcript.tokens[last].end_ms
    fps = contract["native_fps"]
    if type(fps) not in {int, float} or fps <= 0:
        raise ValueError("Native frame rate is not declared")
    used = set()

    def field(path: str, allowed: set[str]) -> None:
        if path not in allowed or path in used:
            raise ValueError("Native path is not allowed or was assigned twice")
        used.add(path)

    def span(begin: str, finish: str) -> list[TranscriptToken]:
        if begin not in positions or finish not in positions:
            raise ValueError("Unknown measured word anchor")
        a, b = positions[begin], positions[finish]
        if not first <= a <= b <= last:
            raise ValueError("Native text/event anchor leaves its meaning span")
        return transcript.tokens[a : b + 1]

    denials = explicit_denial_spans(transcript.tokens) if beat.native_text else []
    texts = []
    text_spans = {}
    for anchor in beat.native_text:
        field(anchor.path, set(contract["text_paths"]))
        tokens = span(anchor.first_token_id, anchor.last_token_id)
        a, b = positions[anchor.first_token_id], positions[anchor.last_token_id]
        if drops_explicit_denial(a, b, denials):
            raise IncompleteDenial("原生文字须保留同一实录分句的否定标记")
        text = emphasis_text("".join(t.text for t in tokens), anchor.punctuation)
        if not text:
            raise ValueError("Native text anchor has no visible content")
        text_spans[anchor.path] = (a, b)
        texts.append(
            {
                "path": anchor.path,
                "text": text,
                "token_ids": [t.id for t in tokens],
                "punctuation_policy": anchor.punctuation,
            }
        )
    if text_spans:
        validate_condition_coverage(
            text_spans.values(), measured_conditions(transcript.tokens)
        )
        validate_quantity_slots(
            beat.group_id, text_spans, measured_quantities(transcript.tokens)
        )
    event_units = {row["path"]: row["unit"] for row in contract["event_paths"]}
    events = []
    for event_anchor in beat.native_events:
        field(event_anchor.path, set(event_units))
        token = span(event_anchor.token_id, event_anchor.token_id)[0]
        measured = token.start_ms if event_anchor.edge == "start" else token.end_ms
        relative = measured - start_ms
        if not 0 <= relative <= end_ms - start_ms:
            raise ValueError("Measured event exceeds current native interval")
        unit = event_units[event_anchor.path]
        if unit == "frames":
            value: int | float = round(relative * fps / 1000)
            quantization = value * 1000 / fps - relative
        elif unit == "seconds":
            value, quantization = relative / 1000, 0.0
        else:
            raise ValueError("Unknown original native time unit")
        events.append(
            {
                "path": event_anchor.path,
                "value": value,
                "unit": unit,
                "token_id": token.id,
                "edge": event_anchor.edge,
                "measured_anchor_ms": measured,
                "frame_quantization_ms": round(quantization, 6),
            }
        )
    media = []
    for media_anchor in beat.native_media:
        field(media_anchor.path, {r["path"] for r in contract["resource_paths"]})
        if (
            media_anchor.asset_id not in allowed_assets
            or media_anchor.asset_id not in beat.asset_ids
        ):
            raise ValueError("Native media is not an available selected project asset")
        media.append({"path": media_anchor.path, "asset_id": media_anchor.asset_id})
    branches = {
        field["native_branch"]
        for field in contract.get("fields", [])
        if field["path"] in used and "native_branch" in field
    }
    if len(branches) > 1:
        raise ValueError("Native anchors cannot mix fields from separate branches")
    return {
        "version": "tengli.native-word-bindings/1",
        "beat_id": beat.id,
        "group_id": beat.group_id,
        "clock": {"start_ms": start_ms, "end_ms": end_ms, "native_fps": fps},
        "text": texts,
        "events": events,
        "media": media,
        "native_schema_validation": "not_performed",
        "runtime_validation": "unverified",
    }
