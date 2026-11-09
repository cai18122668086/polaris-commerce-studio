"""Bind actual presenter source windows through audited native sampling profiles.

This is not a generic offset heuristic. Other media/choreography stays pending
until its original sampling expression has a dedicated, byte-pinned profile.
"""

import math
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
    config: dict,
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
    clips = profile.get("project_clip_event_frames", {})
    cuts = profile.get("transcript_cut_media", {})
    scene_clips = profile.get("project_scene_clip_start_events", {})
    implicit_scene_clips = set(profile.get("project_scene_implicit_extent_paths", []))
    event_bindings = {event["path"]: event for event in native.get("events", [])}
    for row in declarations:
        if set(row) != {"media_path", "policy"} or row["policy"] not in {
            "transcript_source_window",
            "project_clip_from_start",
            "transcript_cut_window",
            "project_scene_clip_window",
        }:
            raise ValueError("Media clock policy must use an audited native slot")
        path = row["media_path"]
        clip = row["policy"] == "project_clip_from_start"
        cut = row["policy"] == "transcript_cut_window"
        scene_clip = row["policy"] == "project_scene_clip_window"
        allowed = (
            clips
            if clip
            else cuts
            if cut
            else scene_clips
            if scene_clip
            else profile["media_paths"]
        )
        if path in used or path not in media or path not in allowed:
            raise ValueError(
                "Media clock must address one selected, audited native slot"
            )
        used.add(path)
        asset = assets[media[path]["asset_id"]]
        if scene_clip:
            clock_fields, receipt = _project_scene_clip(
                path,
                scene_clips[path],
                asset,
                native,
                config,
                media_clock_fields,
                profile,
            )
            assigned.update(clock_fields)
            receipts.append({**receipt, "asset_id": media[path]["asset_id"]})
            continue
        if clip:
            fps = profile["native_fps"]
            shift = config["events"]["shift_frames"]
            if type(shift) is not int:
                raise ValueError("Native clip choreography shift must be an integer")
            fps_window = math.ceil(
                (native["clock"]["end_ms"] - native["clock"]["start_ms"]) / 1000 * fps
            )
            if fps_window <= shift + profile["project_clip_settle_frame"]:
                raise ValueError(
                    "Current scene ends before the native dual-clip transition settles"
                )
            required_ms = math.ceil(
                max(1, fps_window - shift - clips[path]) * 1000 / fps
            )
            if (
                asset.get("kind") != "video"
                or asset.get("source") != "project_upload"
                or type(asset.get("duration_ms")) is not int
                or asset["duration_ms"] < required_ms
            ):
                raise ValueError(
                    "Supplemental clip is missing or shorter than its native window"
                )
            receipts.append(
                {
                    "media_path": path,
                    "asset_id": media[path]["asset_id"],
                    "policy": row["policy"],
                    "source_sha256": asset["sha256"],
                    "source_start_ms": 0,
                    "source_end_ms": required_ms,
                    "asset_duration_ms": asset["duration_ms"],
                    "profile_id": profile["id"],
                    "native_source_files": profile["source_files"],
                    "native_sampling_expression": (
                        f"max(0, (local frame - shift_frames - {clips[path]}) / {fps})"
                    ),
                    "timing_review": "unreviewed",
                }
            )
            continue
        if (
            asset.get("kind") != "original_video"
            or asset.get("sha256") != transcript.source_sha256
        ):
            raise ValueError(
                "Presenter source clock cannot be applied to unrelated project media"
            )
        prefix = path.rsplit("/", 1)[0]
        if (
            implicit_scene_clips
            and config["media"][path.split("/")[2]].get("end_policy") != "error"
        ):
            raise ValueError("Presenter must run without looping or holding")
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
        cut_paths = None
        if cut:
            first, following = cuts[path]
            cut_paths = [first, following]
            boundaries = [event_bindings[p] for p in cut_paths if p is not None]
            if any(
                event["unit"] != "seconds"
                or event["value"] != (event["measured_anchor_ms"] - start) / 1000
                for event in boundaries
            ):
                raise ValueError("Native cuts must use measured local seconds")
            clip_start = boundaries[0]["measured_anchor_ms"]
            clip_end = boundaries[1]["measured_anchor_ms"] if following else end
            if not start <= clip_start < clip_end <= end:
                raise ValueError("Native source cut leaves the measured beat window")
            start, end = clip_start, clip_end
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
                "native_sampling_expression": profile["local_sample_seconds"],
                **({"cut_event_paths": cut_paths} if cut_paths else {}),
                "sampling": (
                    "Original asset_frame rounds to source frames and clamps "
                    "the last frame; no resampling or speed change added"
                ),
                "timing_review": "unreviewed",
            }
        )
    if set(assigned) != media_clock_fields:
        raise ValueError("Every native media offset/duration needs a measured binding")
    if used != selected_videos | (implicit_scene_clips & media.keys()):
        raise ValueError(
            "Each native video or audited still needs its own audited source clock"
        )
    return assigned, receipts


def _project_scene_clip(
    path: str,
    start_event: str | None,
    asset: dict,
    native: dict,
    config: dict,
    media_clock_fields: set[str],
    profile: dict,
) -> tuple[dict[str, float], dict]:
    fps = profile["native_fps"]
    start_frame = 0
    if start_event is not None:
        event = next(
            (row for row in native["events"] if row["path"] == start_event), None
        )
        if not event or event["unit"] != "frames" or type(event["value"]) is not int:
            raise ValueError("Scene clip start needs a measured native frame event")
        start_frame = event["value"]
    duration = native["clock"]["end_ms"] - native["clock"]["start_ms"]
    frames = math.ceil(duration / 1000 * fps)
    if not 0 <= start_frame < frames:
        raise ValueError("Scene clip starts outside the rendered frame window")
    length = (frames - start_frame) / fps
    required_ms = math.ceil((frames - start_frame) * 1000 / fps)
    slot = path.split("/")[2]
    implicit_extent = path in profile.get("project_scene_implicit_extent_paths", [])
    still = implicit_extent and asset.get("kind") == "image"
    if (
        asset.get("source") != "project_upload"
        or config["media"][slot].get("end_policy") != "error"
        or (
            not still
            and (
                asset.get("kind") != "video"
                or type(asset.get("duration_ms")) is not int
                or asset["duration_ms"] < required_ms
            )
        )
    ):
        raise ValueError(
            "Scene clip must cover its native window without looping or holding"
        )
    prefix = path.rsplit("/", 1)[0]
    offset_path = prefix + "/offset_seconds"
    assigned = {offset_path: 0.0}
    if implicit_extent:
        if start_event is not None:
            raise ValueError("This scene slot has no explicit start or duration")
        if offset_path not in media_clock_fields:
            assigned = {}
    else:
        assigned[prefix + "/duration_seconds"] = length
    if start_event is not None:
        assigned[prefix + "/start_seconds"] = start_frame / fps
    if not set(assigned) <= media_clock_fields:
        raise ValueError("Scene clip window differs from the original native fields")
    return assigned, {
        "media_path": path,
        "policy": "project_scene_clip_window",
        "source_sha256": asset["sha256"],
        "source_start_ms": 0,
        "source_end_ms": None if still else required_ms,
        "asset_duration_ms": asset.get("duration_ms"),
        "start_event_path": start_event,
        "start_frame": start_frame,
        "profile_id": profile["id"],
        "native_source_files": profile["source_files"],
        "native_sampling_expression": (
            "Original registered still image"
            if still
            else f"max(0, (local frame - {start_frame}) / {fps})"
        ),
        "timing_review": "unreviewed",
    }
