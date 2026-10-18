"""Bind local model patches to the native effective contracts and shared schema."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from ..config import default_skill_root
from .plans import canonical_hash
from .revision_protocol import RevisionScopeError

PRESERVE = "RESTORE_OR_PRESERVE_APPROVED"
OVERRIDE = "OVERRIDE_LOCAL_FIELDS"


def _invalid(message: str) -> NoReturn:
    raise RevisionScopeError("NATIVE_DETAIL_REVISION_SCOPE_INVALID", message)


def shared_override_schema() -> dict[str, Any]:
    root = default_skill_root("aurora-domestic-ecommerce-detail-page")
    return json.loads(
        (root / "schemas/local-typography-overrides.schema.json").read_bytes()
    )


def _branches() -> dict[str, Any]:
    return {
        row["properties"]["path"]["const"]: row
        for row in shared_override_schema()["items"]["oneOf"]
    }


def effective_contracts(
    plan: Mapping[str, Any],
    module_ids: Sequence[str],
    projection: object = None,
) -> list[dict[str, Any]]:
    """Validate a native projection; it may differ only in supported local leaves."""
    if len(module_ids) != 2 or len(set(module_ids)) != 2:
        _invalid("One ordered adjacent pair is required")
    originals = {m["id"]: m for m in plan["modules"]}
    if any(key not in originals for key in module_ids):
        _invalid("Effective contracts must belong to the approved pair")
    if projection is None:
        projection = [
            {
                "module_id": key,
                "contract": deepcopy(originals[key]),
                "contract_sha256": canonical_hash(originals[key]),
            }
            for key in module_ids
        ]
    if not isinstance(projection, list) or len(projection) != 2:
        _invalid("The actual native effective pair projection is required")
    branches = _branches()
    result = []
    for key, row in zip(module_ids, projection, strict=True):
        if (
            not isinstance(row, Mapping)
            or set(row) != {"module_id", "contract", "contract_sha256"}
            or row["module_id"] != key
            or not isinstance(row["contract"], Mapping)
            or row["contract_sha256"] != canonical_hash(row["contract"])
        ):
            _invalid("Effective contract order, bytes or digest changed")
        original = deepcopy(originals[key])
        contract = deepcopy(dict(row["contract"]))
        for path, branch in branches.items():
            leaf = path.rsplit("/", 1)[1]
            a, b = original.get("text_system"), contract.get("text_system")
            if isinstance(a, dict) and isinstance(b, dict) and leaf in a and leaf in b:
                old, current = a.pop(leaf), b.pop(leaf)
                if canonical_hash(old) != canonical_hash(current):
                    if not Draft202012Validator(
                        branch["properties"]["replacement_value"]
                    ).is_valid(current):
                        _invalid(
                            "An effective typography value violates the native schema"
                        )
                    if isinstance(current, str) and not current.strip():
                        _invalid("An effective typography value cannot be blank")
        if canonical_hash(original) != canonical_hash(contract):
            _invalid("Effective contracts changed facts, copy or unsupported fields")
        result.append(deepcopy(dict(row)))
    return result


def bound_override_schema(context: Mapping[str, Any]) -> dict[str, Any]:
    schema = shared_override_schema()
    selected = next(
        row["contract"]
        for row in context["effective_module_contracts"]
        if row["module_id"] == context["selected_module_id"]
    )
    text = selected.get("text_system") or {}
    choices = []
    for path, branch in _branches().items():
        leaf = path.rsplit("/", 1)[1]
        if leaf not in text:
            continue
        branch = deepcopy(branch)
        properties = branch["properties"]
        properties["module_id"] = {"const": context["selected_module_id"]}
        properties["original_value"] = {"const": deepcopy(text[leaf])}
        properties["change_index"]["maximum"] = (
            len(context["adjustment"]["change_only"]) - 1
        )
        choices.append(branch)
    if choices:
        schema["items"] = {"oneOf": choices}
    else:
        schema["maxItems"] = 0
    return schema


def validate_contract_overrides(
    observation: Mapping[str, Any], context: Mapping[str, Any]
) -> None:
    patches = observation["contract_overrides"]
    selected = next(
        row["contract"]
        for row in context["effective_module_contracts"]
        if row["module_id"] == context["selected_module_id"]
    )
    seen = set()
    by_change: dict[int, list[Any]] = {}
    for patch in patches:
        leaf = patch["path"].rsplit("/", 1)[1]
        if canonical_hash(patch["original_value"]) != canonical_hash(
            selected["text_system"][leaf]
        ):
            _invalid("The exact effective original value and JSON type must match")
        key = patch["module_id"], patch["path"]
        if key in seen:
            _invalid("A local contract leaf cannot be patched twice")
        seen.add(key)
        if canonical_hash(patch["original_value"]) == canonical_hash(
            patch["replacement_value"]
        ):
            _invalid("A local contract replacement must change the effective value")
        if (
            isinstance(patch["replacement_value"], str)
            and not patch["replacement_value"].strip()
        ):
            _invalid("A local contract replacement cannot be blank")
        by_change.setdefault(patch["change_index"], []).append(patch)
    for row in observation["changes"]:
        has_patch = bool(by_change.get(row["index"]))
        if (row["contract_effect"] == OVERRIDE) != has_patch:
            _invalid(
                "Every contract effect must match its exact original change patches"
            )
        if has_patch and (
            context["adjustment"]["change_kind"] != "TYPOGRAPHY_LAYOUT"
            or row["claim_effect"] != "PRESERVE"
            or row["scope"] != "LOCAL"
        ):
            _invalid(
                "Typography overrides cannot authorize new copy, facts or global edits"
            )
