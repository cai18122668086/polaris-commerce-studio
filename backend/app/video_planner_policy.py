"""Explicit JSON planning mode and honest handling of saved empty responses."""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import ApiError
from .video_editing_captioning import text_boundaries
from .video_editing_contracts import Transcript

EMPTY_RESPONSE = "EDITING_PLAN_EMPTY_RESPONSE"


def normalize_material_anchors(
    raw: dict[str, Any], transcript: Transcript
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Keep a material's display anchor inside its declared recorded phrase."""
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    changed = deepcopy(raw)
    repairs = []
    for material in changed.get("materials", []):
        if not isinstance(material, dict):
            continue
        first = material.get("first_token_id")
        last = material.get("last_token_id")
        at = material.get("show_at_token_id")
        if (
            not isinstance(first, str)
            or not isinstance(last, str)
            or not isinstance(at, str)
        ):
            continue
        if any(token not in positions for token in (first, last, at)):
            continue  # Unknown words remain a strict validation failure.
        if positions[first] > positions[last]:
            continue
        target = (
            first
            if positions[at] < positions[first]
            else last
            if positions[at] > positions[last]
            else at
        )
        if target != at and abs(positions[target] - positions[at]) == 1:
            repairs.append(
                {
                    "asset_id": material.get("asset_id", ""),
                    "from": at,
                    "to": target,
                    "reason": "anchor_outside_declared_recorded_phrase",
                }
            )
            material["show_at_token_id"] = target
    return changed, repairs


def normalize_suite_output(
    raw: dict[str, Any], transcript: Transcript, *, repair_caption_lines: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    changed, anchor_repairs = normalize_material_anchors(raw, transcript)
    repairs: list[dict[str, Any]] = [dict(row) for row in anchor_repairs]
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    captions = changed.get("captions")
    if isinstance(captions, list) and captions and isinstance(captions[0], dict):
        first = captions[0].get("first_token_id")
        # A short omitted prefix still belongs to the recorded first caption.
        # Interior gaps, overlaps and unknown words remain strict failures.
        if isinstance(first, str) and first in positions and 0 < positions[first] <= 3:
            captions[0]["first_token_id"] = transcript.tokens[0].id
            repairs.append(
                {"kind": "caption_prefix", "from": first, "to": transcript.tokens[0].id}
            )
    if repair_caption_lines and isinstance(captions, list):
        repairs.extend(_repair_editorial_caption_lines(captions, transcript, positions))
    chapters = changed.get("chapters")
    if isinstance(chapters, list):
        kept = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                kept.append(chapter)
                continue
            first, last = chapter.get("first_token_id"), chapter.get("last_token_id")
            if (
                isinstance(first, str)
                and isinstance(last, str)
                and first in positions
                and last in positions
                and positions[first] <= positions[last]
            ):
                text = ""
                for token in transcript.tokens[positions[first] : positions[last] + 1]:
                    if (
                        text
                        and token.text
                        and re.search(r"[A-Za-z0-9]$", text)
                        and re.match(r"^[A-Za-z0-9]", token.text)
                    ):
                        text += " "
                    text += token.text
                if len(text) > 22:
                    repairs.append(
                        {
                            "kind": "optional_chapter_omitted",
                            "first_token_id": first,
                            "last_token_id": last,
                            "reason": "recorded_text_exceeds_chapter_capacity",
                        }
                    )
                    continue
            kept.append(chapter)
        changed["chapters"] = kept
    return changed, repairs


def _repair_editorial_caption_lines(
    captions: list, transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Fit the recorded phrase within the existing two-line contract."""
    tokens = transcript.tokens
    text = "".join(token.text for token in tokens)
    safe, preferred = text_boundaries(text)
    offsets = [0]
    for token in tokens:
        offsets.append(offsets[-1] + len(token.text))

    def count(start: int, end: int) -> int:
        return len(re.findall(r"\w", text[offsets[start] : offsets[end + 1]]))

    repaired = []
    for cue in captions:
        if not isinstance(cue, dict):
            continue
        first, last = cue.get("first_token_id"), cue.get("last_token_id")
        if (
            not isinstance(first, str)
            or not isinstance(last, str)
            or first not in positions
            or last not in positions
        ):
            continue
        a, b = positions[first], positions[last]
        old = cue.get("line_break_after_token_id")
        if old is not None and (not isinstance(old, str) or old not in positions):
            continue
        spans = cue.get("emphasis", [])
        if not isinstance(spans, list):
            continue
        size = count(a, b)
        emphasis = [
            (positions[item["first_token_id"]], positions[item["last_token_id"]])
            for item in spans
            if isinstance(item, dict)
            and all(
                isinstance(item.get(key), str) and item[key] in positions
                for key in ("first_token_id", "last_token_id")
            )
        ]
        candidates = [
            k
            for k in range(a, b)
            if offsets[k + 1] in safe
            and 1 <= count(a, k) <= 18
            and 1 <= count(k + 1, b) <= 18
            and all(not start <= k < end for start, end in emphasis)
        ]
        if size <= 18 if old is None else positions[old] in candidates:
            continue
        if size <= 18:
            target = None
        elif candidates:
            cut = min(
                candidates,
                key=lambda k: (
                    offsets[k + 1] not in preferred,
                    abs(size - 2 * count(a, k)),
                ),
            )
            target = tokens[cut].id
        else:
            continue
        cue["line_break_after_token_id"] = target
        repaired.append(
            {
                "kind": "editorial_caption_line",
                "first_token_id": first,
                "last_token_id": last,
                "from": old,
                "to": target,
            }
        )
    return repaired


def bind_selected_native_assets(
    raw: dict[str, Any], cards: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    changed = deepcopy(raw)
    allowed = {card["id"] for card in cards}
    repairs = []
    for beat in changed.get("beats", []):
        if not isinstance(beat, dict):
            continue
        media = beat.get("native_media", [])
        if not isinstance(media, list) or any(
            not isinstance(row, dict) for row in media
        ):
            continue
        referenced = {
            row.get("asset_id") for row in media if isinstance(row.get("asset_id"), str)
        }
        assets = beat.get("asset_ids", [])
        if not isinstance(assets, list) or not referenced <= allowed:
            continue  # Never resolve invented or unselected assets.
        missing = sorted(referenced - set(assets))
        if missing:
            beat["asset_ids"] = [*assets, *missing]
            repairs.append(
                {"beat_id": beat.get("id"), "added_selected_assets": missing}
            )
    return changed, repairs


def normalize_azl_windows(
    raw: dict[str, Any], transcript: Transcript, runtime: dict | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rejoin a selected measured window split by an adjacent plain-source beat."""
    changed = deepcopy(raw)
    beats = changed.get("beats", [])
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    windows = (runtime or {}).get("azl_panel_windows", [])
    repairs: list[dict[str, Any]] = []
    if not isinstance(beats, list):
        return changed, repairs
    index = 0
    while index < len(beats):
        beat = beats[index]
        if not isinstance(beat, dict) or not str(beat.get("group_id", "")).startswith(
            "AZL"
        ):
            index += 1
            continue
        for window in windows:
            first, last = window["first_token_id"], window["last_token_id"]
            old_last = beat.get("last_token_id")
            if (
                beat.get("first_token_id") != first
                or beat.get("group_id") not in window["group_ids"]
                or not isinstance(old_last, str)
                or old_last not in positions
                or positions[old_last] >= positions[last]
            ):
                continue
            events = {
                row.get("path"): (row.get("token_id"), row.get("edge"))
                for row in beat.get("native_events", [])
            }
            expected = {
                row["path"]: (row["token_id"], row["edge"])
                for row in window["native_events"]
            }
            media = {
                row.get("asset_id")
                for row in beat.get("native_media", [])
                if row.get("path") != "/media/presenter/path"
            }
            if events != expected or not media <= set(window["material_ids"]):
                continue
            cursor, stop = positions[old_last] + 1, index + 1
            while stop < len(beats) and cursor <= positions[last]:
                following = beats[stop]
                caption_only = all(
                    row.get("path") == "/content/captions/0/text"
                    and row.get("first_token_id") == following.get("first_token_id")
                    and row.get("last_token_id") == following.get("last_token_id")
                    for row in following.get("native_text", [])
                )
                if (
                    following.get("group_id") != "Z-M00"
                    or not caption_only
                    or following.get("native_events")
                    or following.get("relation_items")
                    or any(
                        row.get("path") != "/media/presenter/path"
                        for row in following.get("native_media", [])
                    )
                ):
                    break
                begin, end = (
                    following.get("first_token_id"),
                    following.get("last_token_id"),
                )
                if (
                    begin not in positions
                    or end not in positions
                    or positions[begin] != cursor
                    or positions[end] > positions[last]
                ):
                    break
                cursor, stop = positions[end] + 1, stop + 1
            if cursor == positions[last] + 1:
                consumed = [row.get("id") for row in beats[index + 1 : stop]]
                beat["last_token_id"] = last
                del beats[index + 1 : stop]
                repairs.append(
                    {
                        "beat_id": beat.get("id"),
                        "from_last_token_id": old_last,
                        "to_last_token_id": last,
                        "merged_plain_source_beats": consumed,
                        "policy": "frozen-measured-azl-window/1",
                    }
                )
                break
        index += 1
    return changed, repairs


def json_planning_options(model: str) -> dict[str, Any]:
    # DeepSeek defaults to thinking mode. Its thought tokens share max_tokens
    # with the JSON answer; structured planning needs the final answer instead.
    return {"thinking": {"type": "disabled"}} if model.startswith("deepseek-") else {}


def require_planning_content(response: dict[str, Any]) -> str:
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(
            502,
            EMPTY_RESPONSE,
            "模型未返回编排正文。已保存调用回执，请核对用量；重新生成会产生新的模型费用。",
        )
    return content


def saved_response_empty(provider: Path) -> bool:
    try:
        response = json.loads((provider / "semantic-response.json").read_text("utf8"))
    except (OSError, ValueError):
        return False
    return isinstance(response, dict) and not (
        isinstance(response.get("content"), str) and response["content"].strip()
    )
