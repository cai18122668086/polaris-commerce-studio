"""Explicit JSON planning mode and honest handling of saved empty responses."""

import json
import re
import types
from copy import deepcopy
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from .errors import ApiError
from .video_editing_apple_contracts import AppleSuitePlan, _join
from .video_editing_captioning import text_boundaries
from .video_editing_contracts import Transcript
from .video_editing_reference_text import caption_boundaries
from .video_editing_suite_caption_repair import repair_suite_captions

EMPTY_RESPONSE = "EDITING_PLAN_EMPTY_RESPONSE"
MIN_SUITE_INTRO_MS = 1600
SUITE_POINT_CAPACITY = 24
TITLE_CAPACITY = 20
SUBTITLE_CAPACITY = 32
MATERIAL_MAX_SHIFT_MS = 1500


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
    raw: dict[str, Any],
    transcript: Transcript,
    *,
    features_follow_materials: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    shaped = deepcopy(raw)
    shape_repairs = _repair_plan_shape(shaped, transcript, positions)
    changed, anchor_repairs = normalize_material_anchors(shaped, transcript)
    repairs: list[dict[str, Any]] = [*shape_repairs, *anchor_repairs]
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
    repairs.extend(_fit_opening_title_words(changed, transcript, positions))
    repairs.extend(_fit_suite_display_spans(changed, transcript, positions))
    repairs.extend(_fit_feature_words(changed, transcript, positions))
    repairs.extend(_release_overlapping_closing(changed, positions))
    repairs.extend(_release_points_repeating_closing(changed, positions))
    repairs.extend(_repair_material_order(changed, transcript, positions))
    if features_follow_materials:
        repairs.extend(
            _release_features_before_materials(changed, transcript, positions)
        )
    return changed, repairs


def _nested_model(annotation: Any) -> tuple[type[BaseModel] | None, bool]:
    """The plan sub-model a field holds, and whether it is a list of them."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        for arg in get_args(annotation):
            found = _nested_model(arg)
            if found[0] is not None:
                return found
        return None, False
    if origin is list:
        (item,) = get_args(annotation) or (None,)
        model, _ = _nested_model(item)
        return model, model is not None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    return None, False


def _drop_null_extras(
    value: Any, model: type[BaseModel], path: str, removed: list[str]
) -> None:
    if not isinstance(value, dict):
        return
    fields = model.model_fields
    for key in [k for k in value if k not in fields and value[k] is None]:
        del value[key]
        removed.append(f"{path}{key}")
    for name, info in fields.items():
        child = value.get(name)
        nested, many = _nested_model(info.annotation)
        if nested is None or child is None:
            continue
        if many and isinstance(child, list):
            for index, item in enumerate(child):
                _drop_null_extras(item, nested, f"{path}{name}.{index}.", removed)
        elif not many:
            _drop_null_extras(child, nested, f"{path}{name}.", removed)


def _repair_plan_shape(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Undo two JSON-mode shape slips before the strict schema check.

    The planner runs in json_object mode, so the provider does not enforce
    the output schema. Saved responses (bihuo-33/34) carried an empty extra
    key on every span (``"net": null``) or wrote each caption keyword as
    ``{"<any key>": "<token id>"}``. A null extra field carries nothing and is
    removed. A one-entry keyword naming a real word inside its caption becomes
    the recorded lexical word holding that token. Anything else still fails
    strict validation unchanged.
    """
    if not isinstance(raw, dict):
        return []
    removed: list[str] = []
    _drop_null_extras(raw, AppleSuitePlan, "", removed)
    repairs: list[dict[str, Any]] = []
    if removed:
        repairs.append({"kind": "null_extra_fields_removed", "fields": removed})
    captions = raw.get("captions")
    if not isinstance(captions, list):
        return repairs
    tokens = transcript.tokens
    ends, _ = _word_ends(transcript)
    for cue in captions:
        if not isinstance(cue, dict) or not isinstance(cue.get("emphasis"), list):
            continue
        first = positions.get(str(cue.get("first_token_id")))
        last = positions.get(str(cue.get("last_token_id")))
        if first is None or last is None or first > last:
            continue
        cut_id = cue.get("line_break_after_token_id")
        cut = positions.get(cut_id) if isinstance(cut_id, str) else None
        if cut_id is not None and cut is None:
            continue  # Unknown recorded IDs must still fail strict validation.
        rebuilt: list[Any] = []
        prior = first - 1
        for item in cue["emphasis"]:
            if not (
                isinstance(item, dict)
                and "first_token_id" not in item
                and "last_token_id" not in item
                and len(item) == 1
            ):
                rebuilt.append(item)
                continue
            ((key, ident),) = item.items()
            point = positions.get(ident) if isinstance(ident, str) else None
            if point is None or not first <= point <= last:
                rebuilt.append(item)
                continue
            low, high = first, last
            if cut is not None:
                low, high = (first, cut) if point <= cut else (cut + 1, last)
            start = point
            while start > low and start - 1 not in ends:
                start -= 1
            end = point
            while end < high and end not in ends:
                end += 1
            if len(_join([t.text for t in tokens[start : end + 1]])) > 10:
                start = end = point
            if start <= prior:
                repairs.append(
                    {
                        "kind": "caption_emphasis_dropped",
                        "token_id": ident,
                        "reason": "overlaps_previous_keyword",
                    }
                )
                continue
            span = {
                "first_token_id": tokens[start].id,
                "last_token_id": tokens[end].id,
            }
            rebuilt.append(span)
            prior = end
            repairs.append(
                {
                    "kind": "caption_emphasis_shape_repaired",
                    "key": str(key)[:40],
                    "token_id": ident,
                    "to": span,
                }
            )
        cue["emphasis"] = rebuilt
    return repairs


def _release_features_before_materials(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Apple layout plays feature cards after all materials; omit early ones.

    Features are optional labels; matched project materials are not. A
    feature starting before the last material would reject the whole plan,
    so only that feature is omitted (its words stay in the captions).
    """
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    if not plan.materials or not plan.features:
        return []
    tokens = transcript.tokens
    last = plan.materials[-1]
    point = positions.get(last.show_at_token_id)
    if point is None:
        return []
    last_ms = tokens[point].start_ms if last.edge == "start" else tokens[point].end_ms
    kept, repairs = [], []
    for feature, row in zip(plan.features, raw["features"], strict=True):
        first = positions.get(feature.first_token_id)
        if first is None:
            return []
        if tokens[first].start_ms <= last_ms:
            repairs.append(
                {
                    "kind": "optional_feature_omitted",
                    "first_token_id": feature.first_token_id,
                    "last_token_id": feature.last_token_id,
                    "reason": "feature_before_material_playback",
                }
            )
        else:
            kept.append(row)
    if repairs:
        raw["features"] = kept
    return repairs


FEATURE_CAPACITY = 20


def _fit_feature_words(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Keep feature labels on whole recorded words.

    Features become short labels; the capsule suite shows the last one as its
    conclusion button. The model sometimes binds a feature to part of a word
    (planning 8d64991d: only 「支，」 out of 「随身带一支，」), which renders a
    fragment. Word length is not the test: a single-character word such as
    「稳。」 stays. A feature that cuts a word is widened to its spoken clause
    when that fits, else to its whole words; one that cannot be widened
    without touching its neighbours is omitted (the words stay in captions).
    """
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    if not plan.features:
        return []
    tokens = transcript.tokens
    ends, clauses = _word_ends(transcript)
    intro = positions.get(plan.opening.intro_last_token_id)
    quote = (
        positions.get(plan.quote_start_token_id)
        if plan.quote_start_token_id
        else len(tokens)
    )
    if intro is None or quote is None:
        return []
    spans = []
    for row in plan.features:
        first, last = (
            positions.get(row.first_token_id),
            positions.get(row.last_token_id),
        )
        if first is None or last is None or first > last:
            return []  # unknown words stay a strict validation failure
        spans.append((first, last))
    point_lasts = [
        positions.get(point.last_token_id)
        for point in plan.points
        if positions.get(point.last_token_id) is not None
    ]
    previous = max([intro, *[p for p in point_lasts if p is not None]])

    def text(a: int, b: int) -> str:
        return _join([token.text for token in tokens[a : b + 1]])

    kept: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    for index, (row, (first, last)) in enumerate(
        zip(raw["features"], spans, strict=True)
    ):
        lower = previous + 1
        upper = (spans[index + 1][0] if index + 1 < len(spans) else quote) - 1
        starts = first == 0 or first - 1 in ends
        if starts and last in ends:
            kept.append(row)
            previous = last
            continue
        before = [c for c in clauses if c < first]
        clause = (
            (max(before) + 1 if before else 0),
            min((c for c in clauses if c >= last), default=len(tokens) - 1),
        )
        word_first = first
        while word_first > 0 and word_first - 1 not in ends:
            word_first -= 1
        words = (word_first, min((e for e in ends if e >= last), default=last))
        chosen = None
        for kind, (a, b) in (
            ("feature_clause_fitted", clause),
            ("feature_words_fitted", words),
        ):
            if lower <= a <= b <= upper and len(text(a, b)) <= FEATURE_CAPACITY:
                chosen = (kind, a, b)
                break
        if chosen is None:
            repairs.append(
                {
                    "kind": "optional_feature_omitted",
                    "first_token_id": row["first_token_id"],
                    "last_token_id": row["last_token_id"],
                    "reason": "feature_cuts_a_word",
                }
            )
            continue
        kind, a, b = chosen
        kept.append(
            {**row, "first_token_id": tokens[a].id, "last_token_id": tokens[b].id}
        )
        repairs.append(
            {
                "kind": kind,
                "from": [row["first_token_id"], row["last_token_id"]],
                "to": [tokens[a].id, tokens[b].id],
                "text": text(a, b),
            }
        )
        previous = b
    if repairs:
        raw["features"] = kept
    return repairs


def _word_ends(transcript: Transcript) -> tuple[set[int], set[int]]:
    """Token indexes ending a lexical (jieba) word, and those ending a clause."""
    tokens = transcript.tokens
    lexical, preferred = text_boundaries("".join(token.text for token in tokens))
    offset = 0
    ends, clauses = set(), set()
    for index, token in enumerate(tokens):
        offset += len(token.text)
        if offset in lexical or index == len(tokens) - 1:
            ends.add(index)
        if offset in preferred or index == len(tokens) - 1:
            clauses.add(index)
    return ends, clauses


def _fit_opening_title_words(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Keep the opening title and subtitle on whole recorded words.

    The model sometimes ends the title inside a word (「这款白色头」 +
    「戴耳机，」). Extend the title to the end of that word when it still fits
    the opening and its capacity; otherwise end it at the previous word. A
    subtitle that started right after the old title end follows the new one.
    """
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    tokens = transcript.tokens
    title_a = positions.get(plan.opening.title.first_token_id)
    title_b = positions.get(plan.opening.title.last_token_id)
    sub_a = positions.get(plan.opening.subtitle.first_token_id)
    sub_b = positions.get(plan.opening.subtitle.last_token_id)
    intro = positions.get(plan.opening.intro_last_token_id)
    if None in (title_a, title_b, sub_a, sub_b, intro):
        return []
    assert title_a is not None and title_b is not None and intro is not None
    assert sub_a is not None and sub_b is not None
    if not title_a <= title_b <= intro:
        return []
    ends, clauses = _word_ends(transcript)
    if title_b in ends:
        return []

    def text(a: int, b: int) -> str:
        return _join([token.text for token in tokens[a : b + 1]])

    adjacent = sub_a == title_b + 1
    # Prefer completing the spoken clause (「这款白色头戴耳机，」) over the
    # next jieba word, which may still split a compound (「头戴|耳机」).
    forward = next(
        (
            i
            for i in range(title_b + 1, intro + 1)
            if i in clauses and len(text(title_a, i)) <= TITLE_CAPACITY
        ),
        None,
    ) or next((i for i in range(title_b + 1, intro + 1) if i in ends), None)
    choice = None
    if forward is not None and len(text(title_a, forward)) <= TITLE_CAPACITY:
        new_sub_a = forward + 1 if adjacent or sub_a <= forward else sub_a
        new_sub_b = sub_b
        if new_sub_a > new_sub_b:
            # The subtitle was swallowed by the whole word; let it run on to
            # the next clause end inside the opening, within its capacity.
            clause = set(caption_boundaries(transcript).get("cue_end_token_ids", []))
            new_sub_b = next(
                (
                    i
                    for i in range(new_sub_a, intro + 1)
                    if i in ends
                    and tokens[i].id in clause
                    and len(text(new_sub_a, i)) <= SUBTITLE_CAPACITY
                ),
                -1,
            )
        if new_sub_a <= new_sub_b <= intro and re.search(
            r"[\w㐀-鿿]", text(new_sub_a, new_sub_b)
        ):
            choice = (forward, new_sub_a, new_sub_b)
    if choice is None:
        back = next((i for i in range(title_b - 1, title_a - 1, -1) if i in ends), None)
        if back is None or not re.search(r"[\w㐀-鿿]", text(title_a, back)):
            return []
        new_sub_a = back + 1 if adjacent else sub_a
        if new_sub_a > sub_b or len(text(new_sub_a, sub_b)) > SUBTITLE_CAPACITY:
            new_sub_a = sub_a
        choice = (back, new_sub_a, sub_b)
    end, new_sub_a, new_sub_b = choice
    opening = raw["opening"]
    opening["title"]["last_token_id"] = tokens[end].id
    opening["subtitle"]["first_token_id"] = tokens[new_sub_a].id
    opening["subtitle"]["last_token_id"] = tokens[new_sub_b].id
    return [
        {
            "kind": "opening_title_word_boundary",
            "title_from": text(title_a, title_b),
            "title_to": text(title_a, end),
            "subtitle_from": text(sub_a, sub_b),
            "subtitle_to": text(new_sub_a, new_sub_b),
        }
    ]


def _repair_material_order(
    raw: dict[str, Any], transcript: Transcript, positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Move or drop single material placements that break the body order.

    One image anchored inside the opening (or after the quote, or out of
    speech order) used to reject the whole paid plan. Move such a placement
    to the nearest valid word edge inside its own matched phrase, at most
    MATERIAL_MAX_SHIFT_MS away; otherwise drop just that placement. When no
    placement would remain, leave the plan untouched so it fails strictly.
    """
    try:
        plan = AppleSuitePlan.model_validate(raw)
    except ValidationError:
        return []
    if not plan.materials:
        return []
    tokens = transcript.tokens
    intro = positions.get(plan.opening.intro_last_token_id)
    if intro is None:
        return []
    intro_ms = tokens[intro].end_ms
    quote = (
        positions.get(plan.quote_start_token_id)
        if plan.quote_start_token_id
        else len(tokens)
    )
    if quote is None:
        return []
    quote_ms = tokens[quote].start_ms if quote < len(tokens) else transcript.duration_ms

    def at(index: int, edge: str) -> int:
        return tokens[index].start_ms if edge == "start" else tokens[index].end_ms

    kept: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    prior = -1
    for material, row in zip(plan.materials, raw["materials"], strict=True):
        first = positions.get(material.first_token_id)
        last = positions.get(material.last_token_id)
        point = positions.get(material.show_at_token_id)
        if first is None or last is None or point is None or first > last:
            return []  # Unknown words remain a strict validation failure.
        start = at(point, material.edge)
        if intro_ms <= start < quote_ms and start > prior:
            kept.append(row)
            prior = start
            continue
        options = [
            (abs(at(i, edge) - start), i, edge)
            for i in range(first, last + 1)
            for edge in ("start", "end")
            if intro_ms <= at(i, edge) < quote_ms
            and at(i, edge) > prior
            and abs(at(i, edge) - start) <= MATERIAL_MAX_SHIFT_MS
        ]
        if options:
            _, index, edge = min(options)
            moved = {**row, "show_at_token_id": tokens[index].id, "edge": edge}
            kept.append(moved)
            prior = at(index, edge)
            repairs.append(
                {
                    "kind": "material_placement_moved",
                    "asset_id": material.asset_id,
                    "from": material.show_at_token_id,
                    "from_edge": material.edge,
                    "to": tokens[index].id,
                    "to_edge": edge,
                    "reason": "placement_outside_body_order",
                }
            )
        else:
            repairs.append(
                {
                    "kind": "material_placement_dropped",
                    "asset_id": material.asset_id,
                    "show_at_token_id": material.show_at_token_id,
                    "reason": "no_valid_slot_in_matched_phrase",
                }
            )
    if not repairs or not kept:
        return []
    raw["materials"] = kept
    return repairs


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


def _release_points_repeating_closing(
    raw: dict[str, Any], positions: dict[str, int]
) -> list[dict[str, Any]]:
    """Omit a point card whose words are wholly a closing phrase again.

    A short script's last clause may be planned both as the last point and as
    the first closing layer (bihuo-28 planning 522b996f). The point then starts
    at the quote, so strict order rejects the whole saved response on every
    retry. The closing already shows those spoken words, so only the
    duplicate point is omitted; the words stay in the closing and captions.
    Duplicate feature cards are handled the same way by the suite verifier.
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
    kept, repairs = [], []
    for point, row in zip(plan.points, raw["points"], strict=True):
        first, last = (
            positions.get(point.first_token_id),
            positions.get(point.last_token_id),
        )
        if (
            first is not None
            and last is not None
            and last >= quote
            and any(
                a is not None and b is not None and a <= first <= last <= b
                for a, b in closing
            )
        ):
            repairs.append(
                {
                    "kind": "duplicate_point_omitted",
                    "first_token_id": point.first_token_id,
                    "last_token_id": point.last_token_id,
                    "reason": "point_repeats_closing_phrase",
                }
            )
        else:
            kept.append(row)
    if repairs:
        raw["points"] = kept
    return repairs


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


CHAPTER_TEMPLATE_IDS = frozenset(("unified-chapter-v1", "unified-live-chapters-v1"))
CHAPTER_GROUP_IDS = frozenset(("Z-M05", "Z-M15"))


def normalize_chapter_starts(
    raw: dict[str, Any], template: dict | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Complete a chapter list the model cut short (unified-chapter e2e).

    The chapter templates need one start word per argument_outline item. The
    saved response gave five outline items and five beats, one per item, but
    only the first chapter start, so the whole paid plan was rejected. When
    the beats map one-to-one onto the outline and every given start (and every
    chapter-motion beat) is a beat start, the beat starts are the chapters.
    Anything else still fails strictly.
    """
    if not template or template.get("id") not in CHAPTER_TEMPLATE_IDS:
        return raw, []
    starts = raw.get("chapter_start_token_ids")
    outline = raw.get("argument_outline")
    beats = raw.get("beats")
    if not (
        isinstance(starts, list)
        and starts
        and isinstance(outline, list)
        and isinstance(beats, list)
        and all(isinstance(beat, dict) for beat in beats)
    ) or len(starts) == len(outline):
        return raw, []
    beat_starts = [beat.get("first_token_id") for beat in beats]
    chapter_beats = {
        beat.get("first_token_id")
        for beat in beats
        if beat.get("group_id") in CHAPTER_GROUP_IDS
    }
    if (
        len(beat_starts) != len(outline)
        or len(set(beat_starts)) != len(beat_starts)
        or not all(isinstance(start, str) for start in beat_starts)
        or not set(starts) <= set(beat_starts)
        or not chapter_beats <= set(beat_starts)
    ):
        return raw, []
    changed = deepcopy(raw)
    changed["chapter_start_token_ids"] = beat_starts
    return changed, [
        {
            "kind": "chapter_starts_completed",
            "from": list(starts),
            "to": beat_starts,
            "reason": "one_beat_per_outline_item",
        }
    ]


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
