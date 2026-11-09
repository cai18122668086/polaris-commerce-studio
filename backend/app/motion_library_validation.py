"""Per-group evidence beside the immutable library; history is never approval."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator

from .config import Settings
from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    inside,
    read_json,
    sha256,
    verify_package,
)
from .video_editing_pipeline import environment
from .video_editing_question_branch import QUESTION_BRANCH, QUESTION_GROUP
from .video_editing_question_card import QUESTION_CARD_GROUP, question_card_a_input


def audit(package: Path) -> dict[str, Any]:
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
        groups.append(
            {
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
        )
    return {
        "schema": "tengli.motion-audit/1",
        "release": MOTION_SHA256,
        "created_at": datetime.now(UTC).isoformat(),
        "integrity": integrity,
        "scope": "all entries and template schemas; no render or acceptance implied",
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
        "schema": "tengli.motion-runtime-evidence/1",
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


def group_status(state: Path, group_id: str) -> dict[str, Any]:
    # Called only after resolving group_id against the original catalog.
    directory = inside(state, group_id)
    records = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            value = read_json(path)
            if (
                value.get("release") == MOTION_SHA256
                and value.get("group_id") == group_id
            ):
                records.append(value)
    records.sort(key=lambda r: r["recorded_at"], reverse=True)
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
        "schema": "tengli.motion-runtime-evidence/1",
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
    atomic_json(inside(state, f"{job['group_id']}/{evidence['id']}.json"), evidence)
    return evidence
