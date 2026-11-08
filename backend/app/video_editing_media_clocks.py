"""Bind actual presenter source windows through audited native sampling profiles.

This is not a generic offset heuristic. Other media/choreography stays pending
until its original sampling expression has a dedicated, byte-pinned profile.
"""

from pathlib import Path
from typing import Any

from .motion_library import MOTION_SHA256, read_json, sha256
from .video_editing_contracts import Transcript

MANIFEST = Path(__file__).parent / "data/editing_media_clock_profiles.json"


def clock_profile(group_id: str) -> dict[str, Any] | None:
    data = read_json(MANIFEST)
    if data["library_release"] != MOTION_SHA256:
        raise ValueError("Native sampling profile belongs to another original library")
    return data["profiles"].get(group_id)


def compile_media_clocks(
    package: Path,
    group: dict[str, Any],
    contract: dict,
    native: dict,
    declarations: list[dict],
    assets: dict[str, dict[str, Any]],
    transcript: Transcript,
) -> tuple[dict[str, float], list[dict]]:
    fields = {f["path"]: f for f in contract["fields"]}
    media_clock_fields = {
        path
        for path, field in fields.items()
        if path.startswith("/media/") and field["category"] == "clock_owned_by_compiler"
    }
    selected_videos = {
        m["path"]
        for m in native["media"]
        if assets[m["asset_id"]].get("kind")
        in {"original_video", "video", "generated_video"}
    }
    if not declarations and not media_clock_fields and not selected_videos:
        return {}, []
    if not isinstance(declarations, list):
        raise ValueError("Media clocks need explicit audited declarations")
    profile = clock_profile(group["id"])
    if (
        not profile
        or profile["backend"] != group["backend"]
        or profile["native_fps"] != contract["native_fps"]
    ):
        raise ValueError(
            "This original group still needs an audited media clock profile"
        )
    for path, expected in profile["source_files"].items():
        source = (package / path).resolve()
        if (
            not source.is_relative_to(package.resolve())
            or not source.is_file()
            or sha256(source) != expected
        ):
            raise ValueError("Audited original source-time implementation changed")
    media = {m["path"]: m for m in native["media"]}
    assigned: dict[str, float] = {}
    receipts = []
    used = set()
    for row in declarations:
        if (
            set(row) != {"media_path", "policy"}
            or row["policy"] != "transcript_source_window"
        ):
            raise ValueError("Only measured original presenter windows are implemented")
        path = row["media_path"]
        if path in used or path not in media or path not in profile["media_paths"]:
            raise ValueError(
                "Media clock must address one selected, audited native slot"
            )
        used.add(path)
        asset = assets[media[path]["asset_id"]]
        if (
            asset.get("kind") != "original_video"
            or asset.get("sha256") != transcript.source_sha256
        ):
            raise ValueError(
                "Presenter source clock cannot be applied to unrelated project media"
            )
        prefix = path.rsplit("/", 1)[0]
        offset_path, duration_path = (
            prefix + "/offset_seconds",
            prefix + "/duration_seconds",
        )
        if not {offset_path, duration_path}.issubset(media_clock_fields):
            raise ValueError(
                "Original native template does not expose this source window"
            )
        start, end = native["clock"]["start_ms"], native["clock"]["end_ms"]
        if not 0 <= start < end <= transcript.duration_ms:
            raise ValueError("Presenter window leaves the actual recorded source")
        assigned[offset_path], assigned[duration_path] = (
            start / 1000,
            (end - start) / 1000,
        )
        receipts.append(
            {
                "media_path": path,
                "asset_id": media[path]["asset_id"],
                "policy": row["policy"],
                "source_sha256": transcript.source_sha256,
                "source_start_ms": start,
                "source_end_ms": end,
                "offset_path": offset_path,
                "duration_path": duration_path,
                "profile_id": profile["id"],
                "native_source_files": profile["source_files"],
                "sampling": (
                    "Original asset_frame rounds to source frames and clamps "
                    "the last frame; no resampling or speed change added"
                ),
                "timing_review": "unreviewed",
            }
        )
    if set(assigned) != media_clock_fields:
        raise ValueError("Every native media offset/duration needs a measured binding")
    if used != selected_videos:
        raise ValueError(
            "Every selected native video needs its own audited source clock"
        )
    return assigned, receipts
