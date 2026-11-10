"""Bound user-selected text changes to the original group and recorded words."""

from __future__ import annotations

import re
from typing import Any

from .video_editing_contracts import (
    EditingHighlightChoice,
    EditingHighlightTarget,
    NativeHighlightEdit,
    SemanticBeat,
    SemanticPlan,
    Transcript,
)
from .video_editing_word_bindings import (
    drops_explicit_denial,
    emphasis_text,
    explicit_denial_spans,
)

AUTOMATIC_TEXT_PROFILE = "tengli-overlay-recipe-v2"
# Capacities come from the preserved BG-S04 and AH-S05 native renderers.
_ROLES = {
    "BG-S04": {
        "/content/body": ("/events/body_frame", "左侧竖排词", 4),
        "/content/focus": ("/events/focus_frame", "右侧竖排词", 5),
    },
    "AH-S05": {
        "/content/emphasis": ("/events/emphasis_frame", "跳字强调词", 4),
    },
}
_PROTECTED = re.compile(r"[0-9０-９零一二两三四五六七八九十百千万亿不没无勿别未]")
_BREAK = re.compile(r"[，。！？、；,.!?;]")
_MAX_CHOICES = 32
_MAX_NEARBY_TOKENS = 24


def editable_highlight_roles(
    beat: dict, recipes: dict
) -> dict[str, tuple[str, str, int]]:
    entry = recipes["entries"].get(beat["id"], {})
    recipe = entry.get("recipe", {})
    if (
        recipe.get("design_id") != AUTOMATIC_TEXT_PROFILE
        or recipe.get("group_id") != beat["group_id"]
        or entry.get("placement", {}).get("layer") != "subtitle"
        or beat["relation"] in {"negation", "amount"}
    ):
        return {}
    text = {row["path"]: row for row in beat.get("native_text", [])}
    events = {row["path"]: row for row in beat.get("native_events", [])}
    placeholders = set(recipe.get("placeholders", []))
    return {
        path: (event, label, capacity)
        for path, (event, label, capacity) in _ROLES.get(beat["group_id"], {}).items()
        if path in text
        and event in events
        and {path, event}.issubset(placeholders)
        and events[event]["token_id"] == text[path]["first_token_id"]
        and events[event]["edge"] == "start"
    }


def highlight_targets(
    plan: SemanticPlan,
    recipes: dict,
    transcript: Transcript,
    *,
    all_occurrences: bool = False,
) -> list[EditingHighlightTarget]:
    tokens = transcript.tokens
    positions = {token.id: index for index, token in enumerate(tokens)}
    denials = explicit_denial_spans(tokens)
    result = []
    for beat in plan.beats:
        roles = editable_highlight_roles(beat.model_dump(mode="json"), recipes)
        if not roles:
            continue
        first, last = positions[beat.first_token_id], positions[beat.last_token_id]
        for anchor in beat.native_text:
            if anchor.path not in roles:
                continue
            _, label, capacity = roles[anchor.path]
            old_first, old_last = (
                positions[anchor.first_token_id],
                positions[anchor.last_token_id],
            )
            current = emphasis_text(
                "".join(token.text for token in tokens[old_first : old_last + 1]),
                anchor.punctuation,
            )
            if _PROTECTED.search(current):
                continue
            lower, upper = first, last
            for other in beat.native_text:
                if other.path == anchor.path:
                    continue
                a, b = positions[other.first_token_id], positions[other.last_token_id]
                if b < old_first:
                    lower = max(lower, b + 1)
                elif a > old_last:
                    upper = min(upper, a - 1)
                else:
                    lower, upper = old_first, old_last
            for item in beat.relation_items:
                if anchor.path in item.native_text_paths:
                    lower = max(lower, positions[item.first_token_id])
                    upper = min(upper, positions[item.last_token_id])
            lower = max(lower, old_first - _MAX_NEARBY_TOKENS)
            upper = min(upper, old_last + _MAX_NEARBY_TOKENS)
            cutoff = tokens[last].end_ms
            if beat.group_id == "AH-S05":
                clear = next(
                    (
                        row
                        for row in beat.native_events
                        if row.path == "/events/clear_frame"
                    ),
                    None,
                )
                if clear is None:
                    continue
                clear_token = tokens[positions[clear.token_id]]
                cutoff = (
                    clear_token.start_ms
                    if clear.edge == "start"
                    else clear_token.end_ms
                )
            choices = []
            for a in range(lower, upper + 1):
                raw = ""
                for b in range(a, min(upper + 1, a + capacity)):
                    raw += tokens[b].text
                    if _BREAK.search(raw.rstrip("，。！？、；,.!?;")):
                        break
                    visible = emphasis_text(raw, anchor.punctuation)
                    if len(visible) > capacity or _PROTECTED.search(visible):
                        break
                    if (
                        len(visible) >= 2
                        and visible != current
                        and not drops_explicit_denial(a, b, denials)
                        and tokens[b].end_ms <= cutoff
                        and cutoff - tokens[a].start_ms >= max(250, len(visible) * 60)
                    ):
                        option = EditingHighlightChoice(
                            first_token_id=tokens[a].id,
                            last_token_id=tokens[b].id,
                            text=visible,
                            start_ms=tokens[a].start_ms,
                        )
                        boundary_count = int(
                            a == lower or bool(_BREAK.search(tokens[a - 1].text[-1:]))
                        ) + int(b == upper or bool(_BREAK.search(tokens[b].text[-1:])))
                        choices.append(
                            (
                                (
                                    -boundary_count,
                                    abs(a - old_first) + abs(b - old_last),
                                    a,
                                    b,
                                ),
                                option,
                            )
                        )
            if all_occurrences:
                options = [option for _, option in choices]
            else:
                distinct: dict[str, EditingHighlightChoice] = {}
                for _, option in sorted(choices, key=lambda row: row[0]):
                    distinct.setdefault(option.text, option)
                options = list(distinct.values())[:_MAX_CHOICES]
            if options:
                result.append(
                    EditingHighlightTarget(
                        beat_id=beat.id,
                        path=anchor.path,
                        label=label,
                        current_text=current,
                        options=options,
                    )
                )
    return result


def apply_highlight_edits(
    edits: list[NativeHighlightEdit],
    plan: SemanticPlan,
    recipes: dict,
    transcript: Transcript,
) -> tuple[SemanticPlan, list[dict[str, Any]]]:
    if not edits:
        return plan, []
    available = {
        (target.beat_id, target.path): target
        for target in highlight_targets(plan, recipes, transcript, all_occurrences=True)
    }
    by_beat: dict[str, list[NativeHighlightEdit]] = {}
    for edit in edits:
        by_beat.setdefault(edit.beat_id, []).append(edit)
    if set(by_beat) - {beat.id for beat in plan.beats}:
        raise ValueError("Highlight does not belong to this candidate")
    receipts = []
    beats: list[SemanticBeat] = []
    for beat in plan.beats:
        selected = by_beat.get(beat.id)
        if not selected:
            beats.append(beat)
            continue
        roles = editable_highlight_roles(beat.model_dump(mode="json"), recipes)
        text, events = list(beat.native_text), list(beat.native_events)
        for edit in selected:
            target = available.get((beat.id, edit.path))
            choice = (
                next(
                    (
                        option
                        for option in target.options
                        if (option.first_token_id, option.last_token_id)
                        == (edit.first_token_id, edit.last_token_id)
                    ),
                    None,
                )
                if target
                else None
            )
            if choice is None or target is None:
                raise ValueError(
                    "Highlight is not a supported contiguous recorded phrase"
                )
            old = next(i for i, anchor in enumerate(text) if anchor.path == edit.path)
            event_path, _, _ = roles[edit.path]
            event = next(
                i for i, anchor in enumerate(events) if anchor.path == event_path
            )
            text[old] = text[old].model_copy(
                update={
                    "first_token_id": edit.first_token_id,
                    "last_token_id": edit.last_token_id,
                }
            )
            events[event] = events[event].model_copy(
                update={"token_id": edit.first_token_id}
            )
            receipts.append(
                {
                    **edit.model_dump(mode="json"),
                    "group_id": beat.group_id,
                    "original_text": target.current_text,
                    "applied_text": choice.text,
                    "event_path": event_path,
                    "start_ms": choice.start_ms,
                    "locked_by_user": True,
                }
            )
        beats.append(
            beat.model_copy(update={"native_text": text, "native_events": events})
        )
    return plan.model_copy(update={"beats": beats}), receipts
