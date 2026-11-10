"""Per-group evidence beside the immutable library; history is never approval."""

import hashlib
import json
import math
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator

from .config import Settings
from .motion_browser_originals import (
    BROWSER_ORIGINALS_KEY,
    RENDER_GROUPS,
    require_browser_originals,
    validate_browser_original_receipt,
)
from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    inside,
    read_json,
    sha256,
    verify_package,
)
from .video_editing_browser_boot import (
    BROWSER_BOOT_FONT_GROUPS,
    BROWSER_BOOT_FONT_IDS,
    require_browser_boot_fonts,
)
from .video_editing_hypit_label_cards import (
    LABEL_CARD_GROUP,
    require_label_card_component_font,
)
from .video_editing_pipeline import environment
from .video_editing_question_branch import QUESTION_BRANCH, QUESTION_GROUP
from .video_editing_question_card import QUESTION_CARD_GROUP, question_card_a_input

EVIDENCE_SCHEMA = "tengli.motion-runtime-evidence/1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def motion_evidence_directory(settings: Settings) -> Path:
    """Resolve the evidence for the installed release, outside the original package."""
    root = settings.video_editing_library_evidence_dir
    if root is None:
        root = settings.video_editing_tasks_dir / "_library-validation"
    return root / MOTION_SHA256[:12]


def audit(package: Path, state: Path | None = None) -> dict[str, Any]:
    integrity = verify_package(package)
    groups = []
    for group in read_json(package / "catalog/groups.json")["groups"]:
        schema_path, input_path = (
            package / group["input_schema"],
            package / group["input_template"],
        )
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
        errors = [
            {
                "field": list(e.absolute_path),
                "constraint": e.validator,
                "message": e.message,
            }
            for e in Draft202012Validator(schema).iter_errors(read_json(input_path))
        ]
        group_audit: dict[str, Any] = {
            "group_id": group["id"],
            "backend": group["backend"],
            "entry_sha256": sha256(package / group["entry"]),
            "schema_sha256": sha256(schema_path),
            "template_sha256": sha256(input_path),
            "template_schema_errors": errors,
            "runtime_validation": "unverified",
            "semantic_review": "unreviewed",
            "visual_acceptance": "unreviewed",
        }
        if state is not None:
            runtime = group_status(state, group["id"])
            group_audit.update(
                runtime_validation=runtime["runtime_validation"],
                runtime_evidence_count=len(runtime["runtime_evidence"]),
                runtime_evidence_rejected=runtime["runtime_evidence_rejected"],
            )
        groups.append(group_audit)
    return {
        "schema": "tengli.motion-audit/1",
        "release": MOTION_SHA256,
        "created_at": datetime.now(UTC).isoformat(),
        "integrity": integrity,
        "scope": (
            "all entries, schemas and supplied evidence; no new render or acceptance"
            if state is not None
            else "all entries and template schemas; no render or acceptance implied"
        ),
        "groups": groups,
    }


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def record_native(
    package: Path,
    state: Path,
    instance: Path,
    report_path: Path,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Import a real native render receipt, bound to input/output/library bytes."""
    package, instance = package.resolve(), instance.resolve()
    verify_package(package)
    report = read_json(report_path)
    group_id = report["group_id"]
    groups = {g["id"]: g for g in read_json(package / "catalog/groups.json")["groups"]}
    if group_id not in groups:
        raise ValueError("Unknown original group")
    output = Path(report["output"]).resolve()
    if not output.is_relative_to(instance.resolve()) or not output.is_file():
        raise ValueError("Native output must remain in its instance")
    normalized = inside(instance, f"plans/{output.stem}-native-input.json")
    job = read_json(normalized)
    if (
        job["group_id"] != group_id
        or report.get("library_sha256") != sha256(package / "integrity.json")
        or report.get("public_request_sha256") != canonical_hash(job)
        or not report.get("decoded")
        or report.get("sha256") != sha256(output)
    ):
        raise ValueError("Native receipt, input, library and decoded output disagree")
    boot_fonts = {}
    if group_id in RENDER_GROUPS:
        binding_path = instance / "bindings.json"
        bindings = read_json(binding_path) if binding_path.is_file() else {}
        selected = require_browser_originals(
            package,
            groups[group_id],
            job["config"],
            bindings.get(BROWSER_ORIGINALS_KEY),
            instance / "browser-originals",
        )
        validate_browser_original_receipt(
            group_id, job["config"], selected, report.get("native", {})
        )
        boot_fonts = require_browser_boot_fonts(
            package, groups[group_id], bindings.get("resources", {})
        )
    if group_id == LABEL_CARD_GROUP:
        require_label_card_component_font(
            package,
            job["config"],
            instance / "bindings.json",
            settings.video_editing_native_bindings_file if settings else None,
        )
    encoding = report.get("encoding")
    if groups[group_id].get("backend") == "hypit" and not encoding:
        if not report.get("build_id") or settings is None:
            raise ValueError("Hypit evidence needs its real Build and media tools")
        encoding = measure_encoded_output(output, job, settings)
    elif (
        not encoding
        or not encoding.get("full_decode")
        or encoding.get("frames_written") != report.get("native", {}).get("frames")
    ):
        raise ValueError("Native encoding frame/decode evidence is incomplete")
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "id": uuid4().hex,
        "release": MOTION_SHA256,
        "group_id": group_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "runtime_validation": "sample_rendered",
        "scope": "one concrete native job; other content/resources may still fail",
        "input_sha256": sha256(normalized),
        "receipt_sha256": sha256(report_path),
        "output_sha256": report["sha256"],
        "format": encoding["format"],
        "visual_acceptance": "unreviewed",
        "semantic_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    if group_id in RENDER_GROUPS:
        evidence["browser_originals_checked"] = True
    if boot_fonts:
        evidence["browser_boot_font_ids"] = list(boot_fonts)
    if group_id == LABEL_CARD_GROUP:
        evidence["component_font_use_checked"] = True
    branch = job.get("config", {}).get("branch")
    if job["group_id"] == QUESTION_GROUP and branch in (QUESTION_BRANCH, "smoke"):
        evidence["native_branch"] = branch
    if group_id == QUESTION_CARD_GROUP:
        fonts = job.get("config", {}).get("fonts")
        input_a = read_json(question_card_a_input(package, groups[group_id]))
        input_b = read_json(package / groups[group_id]["input_template"])
        if fonts == input_a["fonts"]:
            evidence["native_branch"] = "input-A"
        elif fonts == input_b["fonts"]:
            evidence["native_branch"] = "input-B"
    _validate_evidence(evidence, group_id, evidence["id"])
    atomic_json(inside(state, f"{group_id}/{evidence['id']}.json"), evidence)
    return evidence


def measure_encoded_output(
    output: Path, job: dict, settings: Settings
) -> dict[str, Any]:
    """Independently decode/count a native output instead of trusting exit status."""
    result = subprocess.run(
        [
            settings.video_editing_ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=60,
        env=environment(settings),
    )
    streams = json.loads(result.stdout)["streams"]
    if len(streams) != 1:
        raise ValueError("Native video stream missing")
    video = streams[0]
    frames = int(video["nb_read_frames"])
    numerator, denominator = map(int, video["avg_frame_rate"].split("/"))
    fps = numerator / denominator
    config = job["config"]
    if (
        frames <= 0
        or fps <= 0
        or ("frames" in config and frames != config["frames"])
        or ("fps" in config and abs(fps - config["fps"]) > 0.001)
        or ("width" in config and video["width"] != config["width"])
        or ("height" in config and video["height"] != config["height"])
    ):
        raise ValueError("Encoded frame clock differs from its current native job")
    subprocess.run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(output),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=300,
        env=environment(settings),
    )
    return {
        "full_decode": True,
        "frames_written": frames,
        "format": {
            "width": video["width"],
            "height": video["height"],
            "fps": fps,
            "frames": frames,
        },
    }


def _validate_evidence(record: Any, group_id: str, evidence_id: str) -> None:
    if (
        not isinstance(record, dict)
        or record.get("schema") != EVIDENCE_SCHEMA
        or record.get("release") != MOTION_SHA256
        or record.get("group_id") != group_id
        or record.get("id") != evidence_id
        or not re.fullmatch(r"[0-9a-f]{32}", evidence_id)
        or record.get("runtime_validation") not in ("sample_rendered", "sample_failed")
        or not isinstance(record.get("scope"), str)
        or not isinstance(record.get("recorded_at"), str)
        or datetime.fromisoformat(record["recorded_at"]).utcoffset() is None
        or any(
            record.get(field) != "unreviewed"
            for field in ("visual_acceptance", "semantic_review", "listening_review")
        )
    ):
        raise ValueError("Invalid native evidence identity")
    hashes = ["input_sha256", "receipt_sha256"]
    if record["runtime_validation"] == "sample_rendered":
        if group_id in BROWSER_BOOT_FONT_GROUPS and record.get(
            "browser_boot_font_ids"
        ) != list(BROWSER_BOOT_FONT_IDS):
            raise ValueError("Browser evidence needs the original startup font check")
        if (
            group_id == LABEL_CARD_GROUP
            and record.get("component_font_use_checked") is not True
        ):
            raise ValueError(
                "HY-A1 evidence needs the original-font component use check"
            )
        if (
            group_id in RENDER_GROUPS
            and record.get("browser_originals_checked") is not True
        ):
            raise ValueError(
                "Browser evidence needs its active original images checked"
            )
        hashes.append("output_sha256")
        format_info = record.get("format")
        if not isinstance(format_info, dict) or any(
            type(format_info.get(field)) is not int or format_info[field] <= 0
            for field in ("width", "height", "frames")
        ):
            raise ValueError("Missing native encoded dimensions or frame count")
        fps = format_info.get("fps")
        if (
            not isinstance(fps, (int, float))
            or isinstance(fps, bool)
            or not math.isfinite(fps)
            or fps <= 0
        ):
            raise ValueError("Missing native encoded frame rate")
    elif record.get("error_code") != "NATIVE_JOB_FAILED":
        raise ValueError("Missing original failure code")
    for field in hashes:
        digest = record.get(field)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("Invalid native evidence digest")


def group_status(state: Path, group_id: str) -> dict[str, Any]:
    # Called only after resolving group_id against the original catalog.
    directory = inside(state, group_id)
    records = []
    rejected = 0
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                if (
                    path.is_symlink()
                    or path.resolve().parent != directory
                    or not path.is_file()
                    or path.stat().st_size > 65_536
                ):
                    raise ValueError(
                        "Runtime evidence is outside the release or oversized"
                    )
                value = read_json(path)
                _validate_evidence(value, group_id, path.stem)
            except (OSError, ValueError, OverflowError):
                rejected += 1
                continue
            records.append(value)
    records.sort(key=lambda r: datetime.fromisoformat(r["recorded_at"]), reverse=True)
    passed = sum(r["runtime_validation"] == "sample_rendered" for r in records)
    failed = len(records) - passed
    return {
        "website_status": "registered",
        "runtime_validation": (
            "mixed_samples"
            if passed and failed
            else "sample_rendered"
            if passed
            else "sample_failed"
            if failed
            else "unverified"
        ),
        "visual_acceptance": "unreviewed",
        "runtime_evidence": records,
        "runtime_evidence_rejected": rejected,
    }


def record_failure(
    package: Path, state: Path, instance: Path, failure_path: Path
) -> dict[str, Any]:
    """Register explicit original CLI failure JSON without exposing private logs."""
    verify_package(package)
    if not failure_path.resolve().is_relative_to(instance.resolve()):
        raise ValueError("Failure evidence must be in its instance")
    job = read_json(instance / "job.json")
    report = read_json(failure_path)
    ids = {g["id"] for g in read_json(package / "catalog/groups.json")["groups"]}
    if (
        job["group_id"] not in ids
        or report.get("status") != "failed"
        or not report.get("error")
    ):
        raise ValueError("Explicit native failure evidence required")
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "id": uuid4().hex,
        "release": MOTION_SHA256,
        "group_id": job["group_id"],
        "recorded_at": datetime.now(UTC).isoformat(),
        "runtime_validation": "sample_failed",
        "error_code": "NATIVE_JOB_FAILED",
        "scope": "one concrete native job failed; group is retained for repair",
        "input_sha256": sha256(instance / "job.json"),
        "receipt_sha256": sha256(failure_path),
        "visual_acceptance": "unreviewed",
        "semantic_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    branch = job.get("config", {}).get("branch")
    if job["group_id"] == QUESTION_GROUP and branch in (QUESTION_BRANCH, "smoke"):
        evidence["native_branch"] = branch
    _validate_evidence(evidence, job["group_id"], evidence["id"])
    atomic_json(inside(state, f"{job['group_id']}/{evidence['id']}.json"), evidence)
    return evidence
