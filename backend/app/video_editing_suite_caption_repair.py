"""Repair suite subtitle layout against the recorded word boundaries."""

from typing import Any

from pydantic import ValidationError

from .video_editing_apple_contracts import PLAN_VERSION, AppleCaption, _join
from .video_editing_caption_emphasis import readable
from .video_editing_captioning import text_boundaries
from .video_editing_contracts import Transcript
from .video_editing_reference_text import caption_boundaries

# Match the strict contract in semantic_caption_rows.
EMPHASIS_CAPACITY = 10
LINE_CAPACITY = 18


def _merge_clause_fragments(
    captions: list, transcript: Transcript, breaks: set[int], widths: list[int]
) -> list[dict[str, Any]]:
    policy = caption_boundaries(transcript)
    if not policy:
        return []
    try:
        cues = [AppleCaption.model_validate(cue) for cue in captions]
    except ValidationError:
        return []

    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    clause_ends = set(policy["cue_end_token_ids"]) | set(
        policy["long_clause_token_ids"]
    )
    sentence_ends = set(policy["sentence_end_token_ids"])
    merged = []
    repairs: list[dict[str, Any]] = []
    index = 0
    while index < len(cues):
        left = cues[index]
        merged.append(captions[index])
        index += 1
        if left.last_token_id in clause_ends or index == len(cues):
            continue
        right = cues[index]
        first = positions.get(left.first_token_id, -1)
        cut = positions.get(left.last_token_id, -1) + 1
        stop = positions.get(right.last_token_id, -1) + 1
        if (
            not 0 <= first < cut < stop
            or positions.get(right.first_token_id) != cut
            or cut not in breaks
            or (first != 0 and first not in breaks)
            or (stop != len(widths) - 1 and stop not in breaks)
            or right.last_token_id not in clause_ends
            or any(
                token.id in sentence_ends
                for token in transcript.tokens[first : stop - 1]
            )
            or not 0 < widths[cut] - widths[first] <= LINE_CAPACITY
            or not 0 < widths[stop] - widths[cut] <= LINE_CAPACITY
        ):
            continue
        # Keep every selected highlight in its original line and preserve strict limits.
        if len(left.emphasis) + len(right.emphasis) > 2 or any(
            not start
            <= positions.get(span.first_token_id, -1)
            <= positions.get(span.last_token_id, -1)
            < end
            for cue, start, end in ((left, first, cut), (right, cut, stop))
            for span in cue.emphasis
        ):
            continue
        if any(
            cue.line_break_after_token_id is not None
            and not start <= positions.get(cue.line_break_after_token_id, -1) < end - 1
            for cue, start, end in ((left, first, cut), (right, cut, stop))
        ):
            continue
        merged[-1] = {
            **captions[index - 1],
            "last_token_id": right.last_token_id,
            "line_break_after_token_id": left.last_token_id,
            "emphasis": [
                *captions[index - 1]["emphasis"],
                *captions[index]["emphasis"],
            ],
        }
        repairs.append(
            {
                "kind": "caption_clause_fragments_joined",
                "first_token_id": left.first_token_id,
                "line_break_after_token_id": left.last_token_id,
                "last_token_id": right.last_token_id,
            }
        )
        index += 1
    captions[:] = merged
    return repairs


def repair_suite_captions(
    plan: dict[str, Any], transcript: Transcript
) -> list[dict[str, Any]]:
    """Adapt a working copy before strict validation."""
    captions = plan.get("captions")
    if plan.get("schema_version", PLAN_VERSION) != PLAN_VERSION or not isinstance(
        captions, list
    ):
        return []
    tokens = transcript.tokens
    parts = [t.text for t in tokens]
    positions = {t.id: i for i, t in enumerate(tokens)}
    offsets = [0]
    widths = [0]
    for part in parts:
        offsets.append(offsets[-1] + len(part))
        widths.append(widths[-1] + readable(part))
    safe, preferred = text_boundaries("".join(parts))
    breaks = {i for i, offset in enumerate(offsets) if offset in safe}
    repairs = _merge_clause_fragments(captions, transcript, breaks, widths)

    def position(value: Any) -> int:
        return positions.get(value, -1) if isinstance(value, str) else -1

    for cue in captions:
        if not isinstance(cue, dict) or not isinstance(cue.get("emphasis"), list):
            continue
        first = position(cue.get("first_token_id"))
        last = position(cue.get("last_token_id"))
        if not 0 <= first <= last:
            continue
        original_cut = cue.get("line_break_after_token_id")
        cut = position(original_cut) + 1
        if original_cut is not None and cut == 0:
            continue  # Unknown recorded IDs must still fail strict validation.
        highlights = cue["emphasis"]
        spans = [
            (position(span.get("first_token_id")), position(span.get("last_token_id")))
            for span in highlights
            if isinstance(span, dict)
        ]
        previous_ends = [first - 1, *(b for _, b in spans)][:-1]
        if len(spans) != len(highlights) or any(
            not previous < a <= b <= last
            for previous, (a, b) in zip(previous_ends, spans, strict=True)
        ):
            continue
        for span, (a, b) in zip(highlights, spans, strict=True):
            if len(_join(parts[a : b + 1])) <= EMPHASIS_CAPACITY:
                continue
            candidates = []
            for start in range(a, b + 1):
                if start and start not in breaks:
                    continue
                for end in range(start + 1, b + 2):
                    phrase = _join(parts[start:end])
                    if len(phrase) > EMPHASIS_CAPACITY:
                        break
                    if (end in breaks or end == len(parts)) and readable(phrase):
                        candidates.append(
                            (
                                first < cut <= last
                                and cut in breaks
                                and start < cut < end,
                                -readable(phrase),
                                -start,
                                end,
                            )
                        )
            if candidates:
                _, _, neg_start, end = min(candidates)
                previous = dict(span)
                span["first_token_id"] = tokens[-neg_start].id
                span["last_token_id"] = tokens[end - 1].id
                repairs.append(
                    {
                        "kind": "caption_emphasis_fitted",
                        "from": previous,
                        "to": dict(span),
                    }
                )

        spans = [
            (positions[span["first_token_id"]], positions[span["last_token_id"]])
            for span in highlights
        ]

        candidates_for_break = {}
        for split in range(first + 1, last + 1):
            left = widths[split] - widths[first]
            right = widths[last + 1] - widths[split]
            if (
                split in breaks
                and 0 < left <= LINE_CAPACITY
                and 0 < right <= LINE_CAPACITY
                and not any(a < split <= b for a, b in spans)
            ):
                candidates_for_break[split] = (
                    offsets[split] not in preferred,
                    max(left, right),
                    abs(split - cut),
                    split,
                )
        if cut in candidates_for_break:
            continue
        if widths[last + 1] - widths[first] <= LINE_CAPACITY:
            new_cut = None
        elif candidates_for_break:
            split = min(candidates_for_break.values())[-1]
            new_cut = tokens[split - 1].id
        else:
            continue
        if new_cut != original_cut:
            cue["line_break_after_token_id"] = new_cut
            repairs.append(
                {
                    "kind": "caption_line_break_fitted",
                    "cue_first_token_id": tokens[first].id,
                    "from": original_cut,
                    "to": new_cut,
                }
            )
    return repairs
