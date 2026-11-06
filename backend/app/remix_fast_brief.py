"""Lossless planner-format compatibility before any fast-remix image request."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from .remix_fast_contract import (
    GEOMETRY_FIELDS,
    PREPARE_PROFILE,
    REFERENCE_FIELDS,
    response_format,
)

WRAPPERS = ("brief", "preparation", "result", "data", "output", "plan")
TEXT_FIELDS = (
    "identity_constraints",
    "page_duty",
    "buyer_conclusion",
    "generation_brief",
)


class BriefFormatError(ValueError):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues[:12]
        super().__init__("Fast remix planning format is invalid")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        response_format(PREPARE_PROFILE)["json_schema"]["schema"]
    )


def _text(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    if (
        isinstance(value, list)
        and value
        and all(isinstance(part, str) and part.strip() for part in value)
    ):
        return "\n".join(part.strip() for part in value)
    return value


def _decode(value: object) -> object:
    if not isinstance(value, str) or len(value) > 150_000:
        return value
    text = value.strip().lstrip("\ufeff").strip()
    fence = re.fullmatch(
        r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*", text, re.I | re.S
    )
    if fence:
        text = fence[1].strip()
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return value


def normalize_brief(value: object) -> dict[str, Any]:
    # Only decode explicit JSON and uniquely identified envelopes. Do not pick
    # a convenient object out of prose or merge two competing candidate plans.
    for _ in range(4):
        decoded = _decode(value)
        if decoded is not value:
            value = decoded
            continue
        if (
            isinstance(value, list)
            and len(value) == 1
            and isinstance(value[0], Mapping)
        ):
            value = value[0]
            continue
        if isinstance(value, Mapping) and not any(
            key in value for key in (*TEXT_FIELDS, "geometry_lock", "reference_facts")
        ):
            candidates = [value[key] for key in WRAPPERS if key in value]
            if len(candidates) == 1:
                value = candidates[0]
                continue
        break
    if not isinstance(value, Mapping):
        raise BriefFormatError([{"path": "/", "rule": "object"}])
    raw = dict(value)
    canonical: dict[str, Any] = {}
    for field, keys in (
        ("geometry_lock", GEOMETRY_FIELDS),
        ("reference_facts", REFERENCE_FIELDS),
    ):
        nested = _decode(raw.get(field, {}))
        if isinstance(nested, Mapping):
            canonical[field] = {
                key: _text(nested[key] if key in nested else raw[key])
                for key in keys
                if key in nested or key in raw
            }
        else:
            canonical[field] = nested
    for key in TEXT_FIELDS:
        if key in raw:
            canonical[key] = _text(raw[key])
    if "approved_visible_copy" in raw:
        copy = raw["approved_visible_copy"]
        if isinstance(copy, str):
            decoded = _decode(copy)
            # A scalar copy string is one literal phrase. Commas, slashes,
            # punctuation and line breaks are never guessed as item separators.
            copy = decoded if isinstance(decoded, list) else [copy]
        canonical["approved_visible_copy"] = copy
    if "product_present" in raw:
        present = raw["product_present"]
        if isinstance(present, str) and present.strip().casefold() in {"true", "false"}:
            present = present.strip().casefold() == "true"
        elif type(present) is int and present in {0, 1}:
            present = bool(present)
        canonical["product_present"] = present
    # critical_regions belonged exclusively to the removed image audit. Legacy
    # responses may still contain it, but it cannot gate planning or delivery.
    errors = list(_validator().iter_errors(canonical))
    if errors:
        raise BriefFormatError(
            [
                {
                    "path": "/" + "/".join(str(part) for part in error.absolute_path),
                    "rule": str(error.validator),
                }
                for error in errors
            ]
        )
    return canonical


def planner_response(
    response: Mapping[str, Any],
) -> tuple[str, object, tuple[str, ...]]:
    """Adapt text blocks and explicit JSON encoding for this profile only."""
    from .xinghe_agent import (
        _planner_content_payload_with_trace,
        _planner_message_text,
    )

    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if (
            isinstance(message, Mapping)
            and isinstance(content, list)
            and content
            and all(
                isinstance(block, Mapping)
                and block.get("type") in {"text", "output_text"}
                and isinstance(block.get("text"), str)
                for block in content
            )
        ):
            # Every block must be text. Refusals or unknown block types cannot
            # be dropped to expose a seemingly usable JSON fragment.
            response = {
                **response,
                "choices": [
                    {
                        **choices[0],
                        "message": {
                            **message,
                            "content": "".join(b["text"] for b in content),
                        },
                    }
                ],
            }
    text = _planner_message_text(response)
    payload, trace = _planner_content_payload_with_trace(text)
    if not isinstance(payload, Mapping):
        try:
            payload = normalize_brief(text)
            trace += ("fast_remix:explicit_encoding_normalized",)
        except BriefFormatError:
            pass
    return text, payload, trace
