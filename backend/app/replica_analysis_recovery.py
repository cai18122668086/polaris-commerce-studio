# ruff: noqa: E501
"""Application admission for explicit analysis correction, without rewriting history."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .replica_native import digest


def document_file(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    record = snapshot.get("files", {}).get(name, {})
    text = record.get("text", "")
    if not text or digest(text.encode()) != record.get("sha256"):
        return {}
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def segmentation_diagnostics(values: dict[str, Any]) -> dict[str, Any] | None:
    if values.get("segmentation_diagnostics"):
        return values["segmentation_diagnostics"]
    snapshot = values.get("_analysis_checkpoint", {})
    inventory = document_file(snapshot, "screen-inventory.json")
    if not inventory:
        # v5 stopped on invalid coverage before writing its inventory summary.
        # Its hash-bound raw observations still live in the durable checkpoint.
        results = list(
            document_file(snapshot, "compact-checkpoints.json")
            .get("results", {})
            .values()
        )
        split_record = next(
            (r for r in reversed(results) if r.get("phase") == "screen_split"), None
        )
        counter_record = next(
            (r for r in reversed(results) if r.get("phase") == "screen_inventory"), None
        )
        if split_record and counter_record:
            from .replica_exact_contracts import canonical_hash

            if all(
                canonical_hash(r.get("raw")) == r.get("response_sha256")
                for r in (split_record, counter_record)
            ):
                inventory = {
                    "split": split_record["raw"],
                    "independent_inventory": counter_record["raw"],
                }
    if inventory.get("diagnostics"):
        return inventory["diagnostics"]
    context = document_file(snapshot, "context.json")
    columns = {c["column_id"]: c for c in context.get("reference_columns", [])}
    split = inventory.get("split", {}).get("columns", [])
    observed = inventory.get("independent_inventory", {}).get("columns", [])
    if not split or len(split) != len(observed):
        return None
    return {
        "version": "legacy-count-summary-v1",
        "coverage_valid": inventory.get("independent_inventory", {}).get(
            "all_columns_covered", False
        ),
        "split_total": sum(len(c.get("screens", [])) for c in split),
        "inventory_total": sum(len(c.get("screens", [])) for c in observed),
        "columns": [
            {
                "column_id": a["column_id"],
                "reference_index": columns.get(a["column_id"], {}).get(
                    "reference_index"
                ),
                "split_count": len(a.get("screens", [])),
                "inventory_count": len(b.get("screens", [])),
                "reason": "count",
            }
            for a, b in zip(split, observed, strict=True)
            if len(a.get("screens", [])) != len(b.get("screens", []))
        ],
    }


def segmentation_repair_available(row: Any, input_hash: str) -> bool:
    values = row.payload
    return bool(
        row.status == "failed"
        and values.get("replication_method") == "exact"
        and values.get("error_code") == "REPLICA_SEGMENTATION_INVALID"
        and not values.get("job_ids")
        and not values.get("plans")
        and values.get("_analysis_input_hash") == input_hash
        and values.get("_analysis_checkpoint", {})
        .get("model_protocol", {})
        .get("version")
        in {"exact-compact-v5", "exact-compact-v6"}
        and segmentation_diagnostics(values)
    )


def style_revision_available(row: Any, input_hash: str) -> bool:
    from .replica_style_analysis import JOURNAL, policy

    values = row.payload
    checkpoint = values.get("_analysis_checkpoint", {})
    return bool(
        row.status == "failed"
        and values.get("replication_method") == "style"
        and values.get("error_code") == "REPLICA_PLAN_AUDIT_REJECTED"
        and not values.get("job_ids")
        and values.get("_analysis_input_hash") == input_hash
        and checkpoint.get("analysis_policy") == policy()
        and document_file(checkpoint, JOURNAL).get("cursor", {}).get("phase")
        == "rejected"
    )


def prepare_segmentation_retry(values: dict[str, Any]) -> dict[str, Any]:
    from .replica_exact_compact import VERSION

    values = dict(values)
    checkpoint = values["_analysis_checkpoint"]
    diagnostic = segmentation_diagnostics(values) or {}
    values["_segmentation_revision"] = {
        "id": uuid4().hex,
        "coverage_retry": diagnostic.get("coverage_valid") is False,
    }
    if checkpoint["model_protocol"]["version"] != VERSION:
        # Keep the complete original snapshot; never relabel old FAILs as new results.
        values["_analysis_lineage"] = [*values.get("_analysis_lineage", []), checkpoint]
        values["_segmentation_parent"] = checkpoint
        values["_exact_model_protocol"] = VERSION
        values.pop("_analysis_checkpoint", None)
        values.pop("_analysis_input_hash", None)
    return values


def configure_run(run: Any, values: dict[str, Any], checkpoint: Any) -> None:
    if values.get("replication_method") == "exact":
        correction = values.get("_segmentation_revision", {})
        run.segmentation_revision = correction.get("id", "initial")
        run.segmentation_coverage_retry = correction.get("coverage_retry", False)
        run.segmentation_parent = values.get("_segmentation_parent")
        if run.segmentation_parent and not checkpoint:
            run.usage = list(run.segmentation_parent.get("usage", []))
            run.cost = int(run.segmentation_parent.get("cost", 0))
    else:
        run.authorized_revision = values.get("_style_revision_requested")
        run.evidence_revision = values.get("analysis_attempt_id", "initial")
        authority = values.get("_style_analysis_revision")
        if (
            authority
            and run.journal.get("cursor", {}).get("applied_revision")
            != run.authorized_revision
        ):
            from .replica_exact_contracts import canonical_hash
            from .replica_native import ReplicaNativeError

            if canonical_hash(checkpoint) != authority.get("parent_snapshot_sha256"):
                raise ReplicaNativeError(
                    "Style correction authority does not match its original snapshot"
                )
