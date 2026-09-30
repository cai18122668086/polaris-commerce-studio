"""One semantic contract for the set reviewer and the local validator."""

from collections.abc import Mapping
from typing import Any

CHECK_NAMES = (
    "page_0_is_search_listing_cover",
    *(f"page_{n}_is_not_search_listing_cover" for n in range(1, 6)),
)


def validate_verdict_fields(payload: Mapping[str, Any]) -> None:
    for key in ("identified_search_page_index", "search_listing_cover_page_index"):
        value = payload.get(key)
        if value is not None and (type(value) is not int or value not in range(6)):
            raise ValueError("invalid_cover_index")
    for key in ("search_role_is_unique", "page_0_alone_is_search_listing_cover"):
        if key in payload and type(payload[key]) is not bool:
            raise ValueError("invalid_uniqueness_verdict")
    if "confusable_page_indexes" in payload:
        indexes = payload["confusable_page_indexes"]
        if not isinstance(indexes, list) or any(
            type(index) is not int or index not in range(6) for index in indexes
        ):
            raise ValueError("invalid_confusable_indexes")


def json_schema() -> dict[str, Any]:
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }

    return obj(
        {
            "checks": {
                "type": "array",
                "minItems": 6,
                "maxItems": 6,
                "items": obj(
                    {
                        "check_name": {"type": "string", "enum": list(CHECK_NAMES)},
                        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
                        "pixel_evidence": {"type": "string", "minLength": 8},
                    }
                ),
            },
            "identified_search_page_index": {
                "type": ["integer", "null"],
                "minimum": 0,
                "maximum": 5,
            },
            "search_role_is_unique": {"type": "boolean"},
            "confusable_page_indexes": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 5},
            },
            "search_identification_evidence": {"type": "string", "minLength": 8},
            "carousel_distinctions": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": obj(
                    {
                        "page_index": {"type": "integer", "minimum": 1, "maximum": 5},
                        "why_not_search_cover": {"type": "string", "minLength": 8},
                    }
                ),
            },
        }
    )


def validate_evidence(payload: dict[str, Any]) -> None:
    """Aliases are accepted only with complete, unambiguous per-page evidence.

    Aggregate-only PASS responses are protocol errors, not visual FAIL verdicts.
    Explicit failures/contradictions are kept by the normalizer, never overridden.
    """
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise ValueError("missing_checks")
    names = []
    for check in checks:
        if not isinstance(check, Mapping):
            raise ValueError("invalid_check")
        aliases = [
            check[key]
            for key in ("check_name", "required_check_name", "name", "check")
            if key in check
        ]
        if not aliases or any(name != aliases[0] for name in aliases):
            raise ValueError("ambiguous_check_name")
        name = aliases[0]
        if name not in CHECK_NAMES:
            raise ValueError("unsupported_check")
        names.append(name)
        statuses = [check[key] for key in ("status", "result") if key in check]
        if not statuses or any(value not in ("PASS", "FAIL") for value in statuses):
            raise ValueError("unknown_check_status")
        evidence = check.get("pixel_evidence")
        if not isinstance(evidence, str) or len(evidence.strip()) < 8:
            raise ValueError("missing_page_evidence")
    if len(names) != 6 or set(names) != set(CHECK_NAMES):
        raise ValueError("incomplete_or_duplicate_page_checks")
    evidence = payload.get("search_identification_evidence")
    if not isinstance(evidence, str) or len(evidence.strip()) < 8:
        raise ValueError("missing_search_evidence")
    distinctions = payload.get("carousel_distinctions")
    if not isinstance(distinctions, list) or len(distinctions) != 5:
        raise ValueError("missing_carousel_evidence")
    indexes = []
    for item in distinctions:
        if not isinstance(item, Mapping):
            raise ValueError("invalid_carousel_evidence")
        indexes.append(item.get("page_index"))
        evidence = item.get("why_not_search_cover")
        if not isinstance(evidence, str) or len(evidence.strip()) < 8:
            raise ValueError("missing_carousel_evidence")
    if any(type(index) is not int for index in indexes) or set(indexes) != set(
        range(1, 6)
    ):
        raise ValueError("incomplete_carousel_evidence")
