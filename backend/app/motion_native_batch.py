"""Run an explicit current-source native cohort; never generate or replace recipes.

Operator manifests include every original group in their chosen backend. A
blocked entry remains recorded, while success means one concrete native sample,
not semantic fitness, production readiness, a whole film or human acceptance.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

from .config import Settings
from .database import build_database
from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    read_json,
    sha256,
    verify_package,
)
from .motion_library_validation import (
    measure_encoded_output,
    record_failure,
    record_native,
)
from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_hypit import hypit_tools
from .video_editing_materials import PREFIX, project_material_files
from .video_editing_native_compiler import compile_native_job
from .video_editing_pipeline import run, stop_hypit_runtimes
from .video_editing_task_models import EditingSourceRecord


def verify_rgba_sequence(root: Path, report: dict, expected_frames: int) -> dict:
    """Require real, varied visible RGBA pixels and exact native sequence bytes."""
    from PIL import Image

    directory = Path(report["rgba_sequence"]).resolve()
    if not directory.is_relative_to(root.resolve()):
        raise ValueError("Native RGBA sequence leaves its current instance")
    sequence = read_json(directory / "sequence.json")
    frames = sequence["frames"]
    if len(frames) != expected_frames or [f["frame"] for f in frames] != list(
        range(expected_frames)
    ):
        raise ValueError("Native RGBA sequence is incomplete or reordered")
    visible, pixel_hashes = [], set()
    for row in frames:
        file = (directory / row["path"]).resolve()
        if not file.is_relative_to(directory) or sha256(file) != row["sha256"]:
            raise ValueError("Native RGBA frame is missing or changed")
        with Image.open(file) as frame:
            if frame.mode != "RGBA" or frame.size != (
                sequence["width"],
                sequence["height"],
            ):
                raise ValueError("Native frame does not preserve the RGBA format")
            if frame.getchannel("A").getbbox():
                visible.append(row["frame"])
            pixel_hashes.add(hashlib.sha256(frame.tobytes()).hexdigest())
    if not visible or len(pixel_hashes) < 2:
        raise ValueError("Native output has no visible motion evidence")
    return {
        "frames_checked": len(frames),
        "visible_frames": len(visible),
        "first_visible_frame": visible[0],
        "last_visible_frame": visible[-1],
        "distinct_pixel_states": len(pixel_hashes),
        "sequence_sha256": sha256(directory / "sequence.json"),
        "scope": "byte, alpha and variation checks; not layout or visual approval",
        "visual_acceptance": "unreviewed",
    }


def verify_scene_motion(
    root: Path, output: Path, expected_frames: int, settings: Settings
) -> dict:
    frame_log = run(
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
            "-map",
            "0:v:0",
            "-an",
            "-f",
            "framemd5",
            "-",
        ],
        root,
        settings,
        lambda: None,
        "decoded_frame_hashes",
    )
    hashes = [
        line.rsplit(",", 1)[1].strip()
        for line in frame_log.read_text(encoding="ascii").splitlines()
        if line and not line.startswith("#")
    ]
    if len(hashes) != expected_frames or len(set(hashes)) < 2:
        raise ValueError(
            "Scene must have the expected decoded frames and real variation"
        )
    return {
        "frames_checked": len(hashes),
        "distinct_decoded_frames": len(set(hashes)),
        "frame_hash_log_sha256": sha256(frame_log),
        "visual_acceptance": "unreviewed",
    }


def validate_manifest(data: dict, package: Path) -> list[dict]:
    if (
        data["version"] != "tengli.native-validation-batch/1"
        or data["library_release"] != MOTION_SHA256
    ):
        raise ValueError("Native batch belongs to a different original release")
    if data["backend"] not in {"subtitle", "scene", "unified", "browser", "hypit"}:
        raise ValueError("Unsupported native cohort evidence backend")
    if data["backend"] != "subtitle" and not data.get("source_asset_id"):
        raise ValueError(
            "Visual cohort needs the current recorded source asset identity"
        )
    groups = read_json(package / "catalog/groups.json")["groups"]
    expected = {g["id"] for g in groups if g["backend"] == data["backend"]}
    actual = [c["group_id"] for c in data["cases"]]
    if not expected or set(actual) != expected or len(actual) != len(expected):
        raise ValueError(
            "Every original group in the selected backend must be recorded"
        )
    for case in data["cases"]:
        if case["disposition"] == "blocked":
            if not case.get("blockers") or not case.get("reason"):
                raise ValueError("Unattempted original entries need explicit blockers")
        elif case["disposition"] == "ready":
            if (
                case["beat"]["group_id"] != case["group_id"]
                or case["recipe"]["group_id"] != case["group_id"]
            ):
                raise ValueError("Batch beat/recipe group identities disagree")
        else:
            raise ValueError("Unknown authoring disposition")
    return data["cases"]


def native_failure(root: Path) -> Path | None:
    # Preserve an actual original diagnostic, not a fabricated native failure.
    for file in (root / "diagnostics").glob("*-last-error.json"):
        try:
            value = read_json(file)
        except (ValueError, OSError):
            continue
        if value.get("status") == "failed" and value.get("error"):
            return file
    return None


def batch_assets(
    data: dict, settings: Settings, source: Path, transcript: Transcript
) -> dict:
    if data["backend"] == "subtitle":
        return {}
    source_id = data["source_asset_id"]
    assets = {
        source_id: {
            "path": str(source),
            "sha256": transcript.source_sha256,
            "kind": "original_video",
        }
    }
    materials = data.get("project_material_ids", [])
    if data["backend"] == "hypit" and not materials:
        raise ValueError(
            "Hypit cohort requires current project media and workspace identity"
        )
    if not materials:
        return assets
    if (
        not source_id.startswith("source-")
        or len(materials) > 24
        or len(set(materials)) != len(materials)
        or any(
            not key.startswith(PREFIX)
            or str(UUID(key.removeprefix(PREFIX))) != key.removeprefix(PREFIX)
            for key in materials
        )
    ):
        raise ValueError(
            "Cohort material inputs require distinct current project identities"
        )
    engine, factory = build_database(settings.database_url)
    try:
        with factory() as session:
            registered = session.get(
                EditingSourceRecord, source_id.removeprefix("source-")
            )
            if (
                not registered
                or registered.media_sha256 != transcript.source_sha256
                or (
                    data["backend"] == "hypit"
                    and registered.workspace_id != data.get("workspace_id")
                )
            ):
                raise ValueError(
                    "Cohort materials must belong to the current registered source"
                )
            return assets | project_material_files(
                session, settings, registered, set(materials), verify_bytes=True
            )
    finally:
        engine.dispose()


def execute(
    manifest: Path,
    root: Path,
    state: Path,
    settings: Settings,
    requested: set[str] | None = None,
    chrome: Path | None = None,
) -> dict[str, Any]:
    package = settings.video_editing_library_dir.resolve()
    if root.resolve().is_relative_to(package) or state.resolve().is_relative_to(
        package
    ):
        raise ValueError(
            "Native cases and evidence must remain outside the original library"
        )
    verify_package(package)
    if manifest.stat().st_size > 8_000_000:
        raise ValueError("Native validation manifest is too large")
    data = read_json(manifest)
    cases = validate_manifest(data, package)
    if chrome is not None and (data["backend"] != "browser" or not chrome.is_file()):
        raise ValueError("Browser evidence needs an installed Chrome executable")
    if requested and not requested <= {c["group_id"] for c in cases}:
        raise ValueError("Requested group is outside the recorded original cohort")
    transcript_file = Path(data["transcript"]["path"]).resolve()
    if sha256(transcript_file) != data["transcript"]["sha256"]:
        raise ValueError("Current measured transcript bytes changed")
    transcript = Transcript.model_validate(read_json(transcript_file))
    source = Path(data["source_path"]).resolve()
    if sha256(source) != transcript.source_sha256:
        raise ValueError("Current source does not match the measured transcript")
    assets = batch_assets(data, settings, source, transcript)
    tools = {}
    if chrome:
        tools = {"chrome": str(chrome.resolve())}
    elif data["backend"] == "hypit":
        workspace_id = data.get("workspace_id")
        tools = hypit_tools(settings, workspace_id)
    root.mkdir(parents=True, exist_ok=False)
    atomic_json(root / "manifest.json", data)
    receipt: dict[str, Any] = {
        "version": "tengli.native-validation-batch-result/1",
        "library_release": MOTION_SHA256,
        "manifest_sha256": sha256(manifest),
        "source_sha256": transcript.source_sha256,
        "transcript_sha256": sha256(transcript_file),
        "backend": data["backend"],
        "cohort_size": len(cases),
        "filter": sorted(requested) if requested else None,
        "new_recognition_alignment_planning_calls": 0,
        "state": "running",
        "cases": [],
        "semantic_review": "unreviewed",
        "visual_acceptance": "unreviewed",
        "scope": "concrete native components from current words, not completed films",
        **({key + "_sha256": sha256(Path(path)) for key, path in tools.items()}),
    }
    for case in cases:
        gid = case["group_id"]
        result: dict[str, Any] = {"group_id": gid}
        instance = root / gid
        if requested and gid not in requested:
            result["status"] = "not_requested"
        elif case["disposition"] == "blocked":
            result.update(
                status="not_attempted", blockers=case["blockers"], reason=case["reason"]
            )
        else:
            try:
                job = compile_native_job(
                    package,
                    instance,
                    SemanticBeat.model_validate(case["beat"]),
                    transcript,
                    case["recipe"],
                    assets,
                    native_bindings_file=settings.video_editing_native_bindings_file,
                )
                if tools:
                    bindings = instance / "bindings.json"
                    atomic_json(
                        bindings,
                        {
                            **read_json(bindings),
                            "tools": tools,
                        },
                    )
                result["status"] = "schema_admitted"
                for command in ("check", "render-group"):
                    run(
                        [
                            settings.video_editing_python or sys.executable,
                            "-B",
                            "-X",
                            "utf8",
                            "-m",
                            "app.video_editing_native",
                            "--package",
                            str(package),
                            "--kind",
                            "group",
                            "--command",
                            command,
                            "--instance",
                            str(instance),
                        ],
                        instance,
                        settings,
                        lambda: None,
                        "native_" + command.replace("-", "_"),
                    )
                report_path = instance / "native-render-group.json"
                report = read_json(report_path)
                output = Path(report["output"]).resolve()
                if output != Path(job["output"]).resolve() or not output.is_relative_to(
                    instance.resolve()
                ):
                    raise ValueError(
                        "Native report does not address this instance's output"
                    )
                measured = measure_encoded_output(output, job, settings)
                if (
                    data["backend"] != "hypit"
                    and measured["format"] != report["encoding"]["format"]
                ):
                    raise ValueError(
                        "Independent decoding differs from native encoding receipt"
                    )
                frame_count = measured["frames_written"]
                if data["backend"] == "subtitle":
                    frame_evidence = {
                        "rgba": verify_rgba_sequence(instance, report, frame_count)
                    }
                else:
                    frame_evidence = {
                        "scene_motion": verify_scene_motion(
                            instance, output, frame_count, settings
                        )
                    }
                atomic_json(
                    instance / "independent-validation.json",
                    {"encoded": measured, **frame_evidence},
                )
                evidence = record_native(
                    package, state, instance, report_path, settings
                )
                result.update(
                    status="sample_rendered",
                    evidence_id=evidence["id"],
                    output_sha256=report["sha256"],
                    measured=measured,
                    **(
                        {"build_id": report["build_id"]}
                        if data["backend"] == "hypit"
                        else {}
                    ),
                    **frame_evidence,
                )
            except Exception as error:
                failure = native_failure(instance)
                if failure and (instance / "job.json").is_file():
                    evidence = record_failure(package, state, instance, failure)
                    result["evidence_id"] = evidence["id"]
                result.update(
                    status="sample_failed" if failure else "adapter_validation_failed",
                    exception_type=type(error).__name__,
                    error=str(error)[:1600],
                )
            finally:
                if data["backend"] == "hypit":
                    stop_hypit_runtimes(instance, settings)
        receipt["cases"].append(result)
        receipt["counts"] = dict(Counter(c["status"] for c in receipt["cases"]))
        atomic_json(root / "batch-receipt.json", receipt)
        print(json.dumps({"group_id": gid, "status": result["status"]}), flush=True)
    verify_package(package)
    receipt.update(state="finished", original_integrity="passed")
    atomic_json(root / "batch-receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--groups", nargs="+")
    parser.add_argument("--chrome", type=Path)
    args = parser.parse_args()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # Pydantic BaseSettings control.
        video_editing_library_dir=args.library,
        video_editing_python=sys.executable,
        video_editing_ffmpeg=args.ffmpeg,
        video_editing_ffprobe=args.ffprobe,
        video_editing_planning_enabled=False,
        video_script_planning_enabled=False,
    )
    result = execute(
        args.manifest,
        args.out,
        args.state_dir,
        settings,
        set(args.groups) if args.groups else None,
        args.chrome,
    )
    print(
        json.dumps({"state": result["state"], "counts": result["counts"]}), flush=True
    )


if __name__ == "__main__":
    main()
