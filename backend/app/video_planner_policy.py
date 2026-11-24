"""Explicit JSON planning mode and honest handling of saved empty responses."""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .errors import ApiError
from .video_editing_apple_contracts import AppleSuitePlan, _join
from .video_editing_captioning import text_boundaries
from .video_editing_contracts import Transcript
from .video_editing_reference_text import caption_boundaries
from .video_editing_suite_caption_repair import repair_suite_captions

EMPTY_RESPONSE = "EDITING_PLAN_EMPTY_RESPONSE"
MIN_SUITE_INTRO_MS = 1600
SUITE_POINT_CAPACITY = 24


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
    raw: dict[str, Any], transcript: Transcript
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
    repairs.extend(repair_suite_captions(changed, transcript))
    repairs.extend(_fit_suite_display_spans(changed, transcript, positions))
    repairs.extend(_release_overlapping_closing(changed, positions))
    return changed, repairs


def _release_overlapping_closing(
    raw: dict[str, Any], positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Omit an optional closing that the planned body itself runs through.

    On a short script the model may mark the last body clauses again as the
    two-part conclusion, so a point or feature card starts at or after the
    quote. The closing is optional; keeping it would reject the whole saved
    response on every retry. Body rows that merely repeat a conclusion phrase
    are left to the existing duplicate handling.
    """
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    if plan.conclusion is None or plan.quote_start_token_id is None:
        return []
    quote = positions.get(plan.quote_start_token_id)
    closing = [
        (positions.get(row.first_token_id), positions.get(row.last_token_id))
        for row in (plan.conclusion.first, plan.conclusion.second)
    ]
    if quote is None or any(a is None or b is None for a, b in closing):
        return []
    rows: list[tuple[str, str]] = [
        *((row.first_token_id, row.last_token_id) for row in plan.points),
        *((row.first_token_id, row.last_token_id) for row in plan.features),
        *((row.show_at_token_id, row.show_at_token_id) for row in plan.materials),
    ]
    for first_id, last_id in rows:
        first, last = positions.get(first_id), positions.get(last_id)
        if first is None or last is None or last < quote:
            continue
        if any(
            a is not None and b is not None and a <= first <= last <= b
            for a, b in closing
        ):
            continue
        raw["conclusion"] = None
        raw["quote_start_token_id"] = None
        return [
            {
                "kind": "optional_closing_omitted",
                "quote_start_token_id": plan.quote_start_token_id,
                "reason": "body_phrase_overlaps_closing",
            }
        ]
    return []


def _fit_suite_display_spans(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Fit opening duration and point labels using existing recorded anchors."""
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    tokens = transcript.tokens
    intro_id = plan.opening.intro_last_token_id
    intro = positions.get(intro_id)
    short_intro = intro is not None and tokens[intro].end_ms < MIN_SUITE_INTRO_MS
    oversized = []
    for index, point in enumerate(plan.points):
        first, last = (
            positions.get(point.first_token_id),
            positions.get(point.last_token_id),
        )
        if (
            first is not None
            and last is not None
            and first < last
            and len(_join([token.text for token in tokens[first : last + 1]]))
            > SUITE_POINT_CAPACITY
        ):
            oversized.append((index, first, last))
    if not short_intro and not oversized:
        return []

    lexical, _ = text_boundaries("".join(token.text for token in tokens))
    offset = 0
    word_ends = set()
    for index, token in enumerate(tokens):
        offset += len(token.text)
        if offset in lexical:
            word_ends.add(index)
    repairs = []

    if short_intro and intro is not None:
        title_ends = [
            positions.get(plan.opening.title.last_token_id),
            positions.get(plan.opening.subtitle.last_token_id),
        ]
        body_anchors = [
            *(point.first_token_id for point in plan.points),
            *(feature.first_token_id for feature in plan.features),
            *(material.show_at_token_id for material in plan.materials),
        ]
        if plan.quote_start_token_id is not None:
            body_anchors.append(plan.quote_start_token_id)
        body_positions = [positions.get(anchor) for anchor in body_anchors]
        if all(end is not None and end <= intro for end in title_ends) and all(
            start is not None and start > intro for start in body_positions
        ):
            # Leave the body content and the original title anchors intact.
            body_start = min(
                (
                    tokens[start].start_ms
                    for start in body_positions
                    if start is not None
                ),
                default=transcript.duration_ms,
            )
            for index in range(intro + 1, len(tokens)):
                token = tokens[index]
                if token.end_ms >= body_start:
                    break
                if index in word_ends and token.end_ms >= MIN_SUITE_INTRO_MS:
                    raw["opening"]["intro_last_token_id"] = token.id
                    repairs.append(
                        {
                            "kind": "opening_duration_fitted",
                            "from": intro_id,
                            "to": token.id,
                        }
                    )
                    break

    clause_ends = set(caption_boundaries(transcript).get("cue_end_token_ids", []))
    for index, first, last in oversized:
        if first and first - 1 not in word_ends:
            continue
        for end in range(first, last):
            tokens_text = _join([token.text for token in tokens[first : end + 1]])
            if len(tokens_text) > SUITE_POINT_CAPACITY:
                break
            if end in word_ends and tokens[end].id in clause_ends:
                raw["points"][index]["last_token_id"] = tokens[end].id
                repairs.append(
                    {
                        "kind": "point_clause_fitted",
                        "from": tokens[last].id,
                        "to": tokens[end].id,
                    }
                )
                break
    return repairs


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
