"""Lossless pixel observations and immutable, single-dispatch vision receipts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker

from ..config import default_skill_root
from .plans import canonical_hash

PAIR_CHECKS = (
    "identity",
    "facts",
    "pair_duties",
    "visual_proof",
    "legibility",
    "copy_binding",
    "internal_seam",
    "spatial_integrity",
    "commercial_expression",
)
IDENTITY_KEYS = ("shape_consistent", "colorway_consistent", "texture_consistent")
AUDIT_PROFILES = frozenset({"aurora_detail_pair_audit", "aurora_detail_identity_audit"})


class DetailReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(path: str, reason: str) -> NoReturn:
    raise DetailReviewError("AURORA_NATIVE_AUDIT_INVALID", f"{path}: {reason}")


def normalize_pair_observation(
    raw: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    image_sha256: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Keep explicit observations; a legacy failure string is a lossless wrapper."""
    value = deepcopy(dict(raw))
    failures = value.get("material_failures")
    if isinstance(failures, list):
        value["material_failures"] = [
            {"visible_evidence": item} if isinstance(item, str) else item
            for item in failures
        ]
    schema = json.loads(
        (
            default_skill_root("aurora-domestic-ecommerce-detail-page")
            / "schemas/pair-judgment.schema.json"
        ).read_bytes()
    )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: str(list(error.absolute_path)),
    )
    if errors:
        error = errors[0]
        parts = [str(part) for part in error.absolute_path]
        if error.validator == "required" and isinstance(error.instance, dict):
            parts.extend(
                [name for name in error.validator_value if name not in error.instance][
                    :1
                ]
            )
        path = "/" + "/".join(parts)
        _invalid(path, "missing, unknown or incorrectly typed pixel observation")
    if value["pair_id"] != request.get("pair_id"):
        _invalid("/pair_id", "does not identify the attached candidate request")
    if value["module_ids"] != request.get("module_ids"):
        _invalid("/module_ids", "does not preserve the approved upper/lower order")
    coverage = value["screen_coverage"]
    if [item["module_id"] for item in coverage] != request.get("module_ids"):
        _invalid("/screen_coverage", "must report both actual windows in order")
    canvas = value["pair_canvas"]
    if (canvas["width_px"], canvas["height_px"]) != (width, height):
        _invalid("/pair_canvas", "dimensions differ from the attached raster")
    binding = value["artifact_binding"]
    if binding["image_sha256"].lower() != image_sha256.lower():
        _invalid("/artifact_binding/image_sha256", "audited raster hash differs")
    for key in ("ocr_text", "unauthorized_ocr_text", "forbidden_text_hits"):
        if not isinstance(value.get(key), list) or any(
            not isinstance(item, str) for item in value[key]
        ):
            _invalid("/" + key, "must explicitly report the observed text list")
    if value["ocr_text"] != binding["ocr_text"]:
        _invalid("/artifact_binding/ocr_text", "disagrees with the raw OCR list")
    if binding["visual_inspection_output"] in (None, "", {}, []):
        _invalid("/artifact_binding/visual_inspection_output", "inspection is absent")
    checks = value["checks"]
    if any(name not in checks for name in PAIR_CHECKS):
        _invalid("/checks", "all nine explicit pair observations are required")
    seam = value["internal_seam_evidence"]
    expected_method = (request.get("pair_render") or {}).get("internal_seam_method_id")
    if not expected_method or seam["method_id"] != expected_method:
        _invalid(
            "/internal_seam_evidence/method_id", "differs from the approved method"
        )
    for key in ("source_region", "target_region", "carrier", "geometry"):
        if len(seam[key].strip()) < 4:
            _invalid(
                "/internal_seam_evidence/" + key, "needs an actual pixel description"
            )
    information = value.get("information_audit")
    if not isinstance(information, dict):
        _invalid("/information_audit", "explicit information observations are required")
    negative = (
        any(checks[name]["pass"] is False for name in PAIR_CHECKS)
        or any(value["identity_silhouette"][name] is False for name in IDENTITY_KEYS)
        or seam["hard_cut_absent"] is False
        or seam["method_specific_pass"] is False
        or any(
            not row["duty_visible"] or not row["selling_points_visible"]
            for row in coverage
        )
        or any(
            information[name] is False
            for name in (
                "new_information_visible",
                "hero_subject_clear",
                "purchase_judgment_enabled",
                "detail_page_not_posterized",
            )
        )
        or information["repetition_without_progression"] is True
        or information["co_equal_hero_detected"] is True
        or bool(value["unauthorized_ocr_text"] or value["forbidden_text_hits"])
    )
    if value["status"] == "PASS" and (negative or value["material_failures"]):
        _invalid("/status", "PASS contradicts explicit negative observations")
    if value["status"] == "MATERIAL_FAIL" and not value["material_failures"]:
        _invalid(
            "/material_failures", "a paid image repair needs a visible material finding"
        )
    return value


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class ReviewStore:
    root: Path
    binding: Mapping[str, Any]

    @property
    def sha256(self) -> str:
        return canonical_hash(self.binding)

    @property
    def stem(self) -> Path:
        key = base64.urlsafe_b64encode(bytes.fromhex(self.sha256)).decode().rstrip("=")
        return self.root / key

    @property
    def request_path(self) -> Path:
        return self.stem.with_suffix(".request.json")

    @property
    def response_path(self) -> Path:
        return self.stem.with_suffix(".response.json")

    def completed(self) -> dict[str, Any] | None:
        if not self.request_path.exists():
            for path in self.root.glob("*.request.json"):
                old = json.loads(path.read_bytes()).get("binding")
                if not isinstance(old, dict):
                    raise DetailReviewError(
                        "AURORA_NATIVE_REVIEW_CHANGED",
                        "Existing review request is invalid",
                    )
                if all(
                    old.get(key) == self.binding.get(key)
                    for key in (
                        "phase",
                        "render_token",
                        "native_request_sha256",
                        "candidate_sha256",
                    )
                ):
                    raise DetailReviewError(
                        "AURORA_NATIVE_REVIEW_BINDING_CHANGED",
                        (
                            "Reconcile the existing review before changing "
                            "code, model or sources"
                        ),
                    )
            return None
        if json.loads(self.request_path.read_bytes()).get("binding") != self.binding:
            raise DetailReviewError(
                "AURORA_NATIVE_REVIEW_CHANGED", "Review request changed"
            )
        if not self.response_path.exists():
            raise DetailReviewError(
                "AURORA_NATIVE_REVIEW_OUTCOME_UNKNOWN",
                "Reconcile the original vision request before another paid review",
            )
        response = json.loads(self.response_path.read_bytes())
        result = response.get("result")
        if (
            not isinstance(result, dict)
            or response.get("binding_sha256") != self.sha256
            or response.get("result_sha256") != canonical_hash(result)
            or response.get("response") != result.get("payload")
        ):
            raise DetailReviewError(
                "AURORA_NATIVE_REVIEW_CHANGED", "Raw review receipt changed"
            )
        raw = response.get("raw_reply")
        original = result.get("audit_raw_content")
        if isinstance(original, str) != isinstance(raw, dict):
            raise DetailReviewError(
                "AURORA_NATIVE_REVIEW_CHANGED", "Raw reply receipt is inconsistent"
            )
        if isinstance(raw, dict):
            content = self.stem.with_suffix(".reply.txt").read_bytes()
            if (
                hashlib.sha256(content).hexdigest() != raw.get("sha256")
                or content != str(original).encode("utf-8")
                or len(content) != raw.get("bytes")
            ):
                raise DetailReviewError(
                    "AURORA_NATIVE_REVIEW_CHANGED", "Raw reply bytes changed"
                )
        return result

    def begin(self) -> None:
        try:
            _write_once(self.request_path, {"binding": dict(self.binding)})
        except FileExistsError as exc:
            raise DetailReviewError(
                "AURORA_NATIVE_REVIEW_ALREADY_DISPATCHED",
                "This exact vision request was already dispatched",
            ) from exc

    def finish(self, result: Mapping[str, Any]) -> None:
        raw = result.get("audit_raw_content")
        raw_receipt = None
        if isinstance(raw, str):
            content = raw.encode("utf-8")
            with self.stem.with_suffix(".reply.txt").open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            raw_receipt = {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        _write_once(
            self.response_path,
            {
                "binding_sha256": self.sha256,
                "result": dict(result),
                "result_sha256": canonical_hash(result),
                "response": result.get("payload"),
                "raw_reply": raw_receipt,
                "raw_reply_state": "original_message_utf8"
                if raw_receipt
                else "predecoded_only",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
