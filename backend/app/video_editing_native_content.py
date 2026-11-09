"""Compile original native labels from current source anchors."""

import re
from typing import Any

from .video_editing_contracts import SemanticBeat, Transcript

CHAPTER_GROUPS = frozenset(("Z-M05", "Z-M15"))
CHAPTER_PATH = "/content/ordinal"
NUMBER_GROUP = "W-R07"
TRANSLATION_GROUP = "W-R02"
_ORDINALS = (
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
)
_DIGITS = dict(zip("零一二三四五六七八九两", "01234567892", strict=True))
_NUMBER = re.compile(
    r"([0-9]{1,3}|[零一二两三四五六七八九十])"
    r"(千克|公斤|毫升|斤|克|升|瓶|件|个|包|盒|元|块|条|天)?"
)
_ENGLISH_LABEL = re.compile(r"[A-Z]+(?:[ -][A-Z]+)*")


def chapter_ordinal(
    beat: SemanticBeat, transcript: Transcript, markers: Any
) -> dict[str, Any]:
    positions = {token.id: index for index, token in enumerate(transcript.tokens)}
    if (
        beat.group_id not in CHAPTER_GROUPS
        or not isinstance(markers, list)
        or not 1 <= len(markers) <= len(_ORDINALS)
        or any(
            not isinstance(token, str) or token not in positions for token in markers
        )
    ):
        raise ValueError("Original chapter ordinal requires measured outline anchors")
    ordered = [positions[token] for token in markers]
    if ordered[0] != 0 or ordered != sorted(set(ordered)):
        raise ValueError(
            "Chapter outline must start at the first word and follow source order"
        )
    if beat.first_token_id not in markers:
        raise ValueError("Native chapter must start on its saved outline anchor")
    index = markers.index(beat.first_token_id)
    if index + 1 < len(ordered) and positions[beat.last_token_id] >= ordered[index + 1]:
        raise ValueError("Native chapter leaves its saved outline interval")
    return {
        "chapter_number": index + 1,
        "chapter_start_token_ids": markers,
        "current_start_token_id": beat.first_token_id,
        "display_text": _ORDINALS[index],
    }


def number_glyphs(native: dict[str, Any]) -> list[dict[str, Any]]:
    rows = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    readings = []
    for index in range(2):
        path = f"/content/numbers/{index}"
        number = rows.get(path)
        caption = rows.get(f"/content/captions/{index}")
        if not number or not caption:
            raise ValueError("Each native number needs a spoken amount and its caption")
        match = _NUMBER.fullmatch(number["text"])
        caption_tokens = caption["token_ids"]
        amount_tokens = number["token_ids"]
        if not match or not any(
            caption_tokens[start : start + len(amount_tokens)] == amount_tokens
            for start in range(len(caption_tokens))
        ):
            raise ValueError("Bind a supported spoken integer within its own caption")
        event_name = "black_in" if index == 0 else "second_number"
        event = events.get(f"/timing/events/{event_name}")
        if (
            not event
            or event["token_id"] != amount_tokens[0]
            or event["edge"] != "start"
        ):
            raise ValueError(
                "Each original number reveal needs its spoken amount start"
            )
        spoken, unit = match.groups()
        digits = "10" if spoken == "十" else _DIGITS.get(spoken, spoken)
        readings.append({**number, "display_text": digits, "unit": unit})
    label = rows.get("/content/label", {}).get("text")
    first, second = readings
    if first["unit"] != second["unit"] or (first["unit"] and label != first["unit"]):
        raise ValueError("Native comparison must preserve the same spoken unit")
    return readings


def translation_labels(native: dict[str, Any], authored: Any) -> list[dict[str, Any]]:
    """Keep the trusted recipe's English glosses separate from spoken words."""
    sides = ("before", "after")
    if (
        native["group_id"] != TRANSLATION_GROUP
        or not isinstance(authored, dict)
        or set(authored) != set(sides)
    ):
        raise ValueError(
            "Native translation requires the original two-sided label group"
        )
    spoken = {row["path"]: row for row in native["text"]}
    result = []
    for side in sides:
        path = f"/content/english_{side}"
        source_path = f"/content/{side}"
        source = spoken.get(source_path)
        caption = spoken.get(f"/content/caption_{side}")
        row = authored[side]
        if (
            path in spoken
            or not source
            or not caption
            or not isinstance(row, dict)
            or set(row) != {"source_text", "display_text"}
            or row["source_text"] != source["text"]
            or not set(source["token_ids"]) <= set(caption["token_ids"])
        ):
            raise ValueError(
                "Each translation must reference its own spoken label and caption"
            )
        display = row["display_text"]
        if (
            not isinstance(display, str)
            or len(display) > 24
            or not _ENGLISH_LABEL.fullmatch(display)
        ):
            raise ValueError(
                "Use a short uppercase English label in the native translation"
            )
        result.append(
            {
                "path": path,
                "source_path": source_path,
                "source_text": source["text"],
                "source_token_ids": source["token_ids"],
                "display_text": display,
                "origin": "trusted_recipe",
                "semantic_review": "unreviewed",
            }
        )
    return result
