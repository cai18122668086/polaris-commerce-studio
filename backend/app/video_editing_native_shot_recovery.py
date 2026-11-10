"""Relocate sealed shots so the pinned native exporter can verify and reuse them."""

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .motion_library import atomic_json, read_json, sha256
from .video_editing_delivery_checkpoint import normalize_attempt_paths

_PINNED = {
    "adapter.py": "2e21e9639c9398164ba05f2e63444d510378621445fdf57be1f66380ee44212e",
    "commercial_runtime/episode.py": (
        "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038"
    ),
    "commercial_runtime/worker.py": (
        "6c05875480b9ce6a3ad74c578d6fb1431cc98b20f255f62265a86530323d8bb7"
    ),
}
_ADAPTERS = (
    "native",
    "native_compat",
    "native_font_maps",
    "native_shot_recovery",
    "hypit_strips",
    "browser_live",
    "browser_rotation",
    "browser_original_transport",
    "line_branch",
    "question_branch",
)
_REJECTED = (OSError, ValueError, TypeError, KeyError, AttributeError)


def _request_sha(job: dict) -> str:
    return hashlib.sha256(
        json.dumps(job, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _file(path: Path) -> Path:
    if path.resolve() != path or not path.is_file():
        raise ValueError("Expected a regular file within the attempt")
    return path


def _job_file(root: Path, output: Path) -> Path:
    return root / "plans" / (output.stem + "-native-input.json")


def _seal_file(root: Path, output: Path) -> Path:
    return root / "native-shot-checkpoints" / output.with_suffix(".json").name


def _seal(root: Path, output: Path, receipt: dict, restored_from: str | None) -> None:
    if receipt.get("decoded") is not True or not receipt.get("encoding", {}).get(
        "full_decode"
    ):
        return
    sequence = output.with_name(output.stem + "-rgba") / "sequence.json"
    atomic_json(
        _seal_file(root, output),
        {
            "request_file_sha256": sha256(_job_file(root, output)),
            "receipt_file_sha256": sha256(output.with_suffix(".receipt.json")),
            "output_sha256": receipt["sha256"],
            "sequence_sha256": sha256(sequence)
            if receipt.get("rgba_sequence")
            else None,
            "restored_from": restored_from,
        },
    )


def _copy_checked(source: Path, target: Path, digest: str) -> None:
    shutil.copyfile(_file(source), target)
    if sha256(target) != digest:
        raise ValueError("Native shot bytes changed")


def _stage_shot(
    staged: Path,
    previous: Path,
    root: Path,
    output: Path,
    job: dict,
    library_sha: str,
    subtitle: bool,
) -> dict:
    old_output = previous / "renders" / output.name
    seal = read_json(_file(_seal_file(previous, old_output)))
    old_request = _file(_job_file(previous, old_output))
    old_receipt = _file(old_output.with_suffix(".receipt.json"))
    if (
        sha256(old_request) != seal["request_file_sha256"]
        or sha256(old_receipt) != seal["receipt_file_sha256"]
    ):
        raise ValueError("Sealed native request or receipt changed")
    prior_job, receipt = read_json(old_request), read_json(old_receipt)
    if (
        receipt["decoded"] is not True
        or receipt["encoding"]["full_decode"] is not True
        or receipt["library_sha256"] != library_sha
        or receipt["public_request_sha256"] != _request_sha(prior_job)
        or receipt["group_id"] != job["group_id"]
        or receipt["output"] != str(old_output)
        or receipt["sha256"] != seal["output_sha256"]
        or bool(receipt.get("rgba_sequence")) != subtitle
        or normalize_attempt_paths(prior_job, previous)
        != normalize_attempt_paths(job, root)
    ):
        raise ValueError("Native shot input or receipt differs")
    _copy_checked(old_output, staged / "shot.mp4", receipt["sha256"])
    receipt["output"] = receipt["encoding"]["output"] = str(output)
    receipt["public_request_sha256"] = _request_sha(job)
    if subtitle:
        folder = old_output.with_name(old_output.stem + "-rgba")
        if receipt["rgba_sequence"] != str(folder):
            raise ValueError("Native sequence is outside its shot")
        rgba = staged / "rgba"
        rgba.mkdir()
        _copy_checked(
            folder / "sequence.json", rgba / "sequence.json", seal["sequence_sha256"]
        )
        sequence = read_json(rgba / "sequence.json")
        if len(sequence["frames"]) != receipt["native"]["frames"]:
            raise ValueError("Native sequence is incomplete")
        for number, frame in enumerate(sequence["frames"]):
            name = f"{number:06}.png"
            if frame["frame"] != number or frame["path"] != name:
                raise ValueError("Native sequence frame ordering changed")
            _copy_checked(folder / name, rgba / name, frame["sha256"])
        receipt["rgba_sequence"] = str(output.with_name(output.stem + "-rgba"))
    return receipt


def _restore_shot(
    previous: Path,
    root: Path,
    output: Path,
    job: dict,
    library_sha: str,
    subtitle: bool,
) -> bool:
    output.parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".shot-", dir=output.parent) as folder:
        staged = Path(folder)
        try:
            receipt = _stage_shot(
                staged, previous, root, output, job, library_sha, subtitle
            )
        except _REJECTED:
            return False
        if subtitle:
            os.replace(staged / "rgba", output.with_name(output.stem + "-rgba"))
        atomic_json(output.with_suffix(".receipt.json"), receipt)
        os.replace(staged / "shot.mp4", output)
    return True


def _matches_shot_clock(receipt: dict, duration: float, episode_fps: float) -> bool:
    try:
        timing = receipt["encoding"]["format"]
        rate, frames = float(timing["fps"]), int(timing["frames"])
    except (ValueError, TypeError, KeyError):
        return False
    return (
        rate > 0
        and frames > 0
        and math.isfinite(rate)
        and abs(frames / rate - duration) <= max(1 / rate, 1 / episode_fps) + 0.001
    )


def _verify_hypit_encoding(
    output: Path, receipt: dict, duration: float, fps: float
) -> dict:
    if receipt.get("decoded") is not True or receipt["sha256"] != sha256(output):
        raise ValueError("Original Hypit build does not match its encoded shot")
    observed = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames,avg_frame_rate,width,height",
            "-of",
            "json",
            str(output),
        ],
        timeout=120,
    )
    (video,) = json.loads(observed)["streams"]
    rate = float(Fraction(video["avg_frame_rate"]))
    encoding = {
        "output": str(output),
        "full_decode": True,
        "format": {
            "fps": rate,
            "frames": int(video["nb_read_frames"]),
            "width": int(video["width"]),
            "height": int(video["height"]),
        },
    }
    result = {**receipt, "encoding": encoding}
    if rate != fps or not _matches_shot_clock(result, duration, fps):
        raise ValueError("Hypit decoded frame clock does not fit the episode")
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ],
        check=True,
        timeout=120,
    )
    atomic_json(output.with_suffix(".receipt.json"), result)
    return result


def _preview_reuse_identity(root: Path) -> str | None:
    """Compare source, bindings and renderer dependencies across previews."""
    try:
        bindings = read_json(root / "bindings.json")
        tools = bindings.get("tools", {})
        binary_digests = {}
        for name in ("ffmpeg", "ffprobe"):
            executable = tools.get(name) or shutil.which(name)
            if not executable:
                return None
            binary_digests[name] = sha256(Path(executable))
        return _request_sha(
            {
                "source_sha256": read_json(root / "prepared.json")["source_sha256"],
                "bindings": normalize_attempt_paths(bindings, root),
                "tools": binary_digests,
                "platform": sys.platform,
                "pillow": version("Pillow"),
                "numpy": version("numpy"),
            }
        )
    except (*_REJECTED, PackageNotFoundError):
        return None


def _earlier_preview(root: Path, plan: dict, marker: dict) -> Path | None:
    name = plan.get("preview_base_attempt")
    if not name or not marker.get("preview_reuse_identity"):
        return None
    try:
        candidate = Path(name)
        if (
            candidate != candidate.resolve()
            or candidate.parent.parent != root.parent.parent
            or candidate.parent == root.parent
            or not re.fullmatch(r"[0-9a-f]{8}", candidate.name)
        ):
            return None
        previous = read_json(_file(candidate / "native-shot-resume.json"))
        keys = ("version", "python", "adapter_sources", "preview_reuse_identity")
        if all(previous.get(key) == marker[key] for key in keys):
            return candidate
    except _REJECTED:
        pass
    return None


def install_shot_recovery(package: Path, root: Path) -> None:
    plan = root / "native-shot-plan.json"
    if not plan.is_file() or any(
        sha256(package / path) != digest for path, digest in _PINNED.items()
    ):
        return
    compiled = read_json(plan)
    marker = {
        "version": "tengli.native-shots/1",
        "compiled_sha256": compiled["compiled_sha256"],
        "python": sys.version,
        "preview_reuse_identity": _preview_reuse_identity(root),
        "adapter_sources": [
            sha256(Path(__file__).with_name(f"video_editing_{name}.py"))
            for name in _ADAPTERS
        ],
    }
    atomic_json(root / "native-shot-resume.json", marker)
    earlier_preview = _earlier_preview(root, compiled, marker)
    candidates = []
    for prior in sorted(root.parent.iterdir()):
        if prior == root or not re.fullmatch(r"[0-9a-f]{8}", prior.name):
            continue
        try:
            if read_json(_file(prior / "native-shot-resume.json")) == marker:
                candidates.append(prior)
        except _REJECTED:
            continue

    sys.path.insert(0, str(package))
    try:
        adapter: Any = importlib.import_module("adapter")
    finally:
        sys.path.pop(0)
    if Path(adapter.__file__).resolve() != package / "adapter.py":
        return
    original = adapter.worker
    library_sha = sha256(package / "integrity.json")
    groups = read_json(package / "catalog/groups.json")["groups"]
    subtitles = {row["id"] for row in groups if row["kind"] == "subtitle"}
    standalone_subtitles = {row["id"] for row in groups if row["backend"] == "subtitle"}
    hypit = {row["id"] for row in groups if row["backend"] == "hypit"}
    episode = read_json(root / "episode.json")
    duration = {
        f"{index:03}-{shot['group_id']}.mp4": shot["end_seconds"]
        - shot["start_seconds"]
        for index, shot in enumerate(episode["shots"])
    }
    fps = episode["output"]["fps"]

    def worker(operation: str, job: dict, instance: Path, args: Any) -> dict:
        output = Path(job["output"])
        if (
            operation != "render"
            or instance != root
            or output.parent != root / "renders"
            or output.name not in duration
        ):
            return original(operation, job, instance, args)
        if job["group_id"] in hypit:
            # Retain the build receipt and its live task files together.
            return _verify_hypit_encoding(
                output,
                original(operation, job, instance, args),
                duration[output.name],
                fps,
            )
        restored_from = None
        for prior in candidates:
            if _restore_shot(
                prior, root, output, job, library_sha, job["group_id"] in subtitles
            ):
                restored_from = prior.name
                break
        if (
            restored_from is None
            and earlier_preview
            and job["group_id"] in standalone_subtitles
            and _restore_shot(earlier_preview, root, output, job, library_sha, True)
        ):
            restored_from = (
                f"preview:{earlier_preview.parent.name}/{earlier_preview.name}"
            )
        receipt = original(operation, job, instance, args)
        if _matches_shot_clock(receipt, duration[output.name], fps):
            _seal(root, output, receipt, restored_from)
        return receipt

    adapter.worker = worker
