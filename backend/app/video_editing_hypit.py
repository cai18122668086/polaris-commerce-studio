"""Adapt the original HY-A3 three-picture profile and restrict local execution."""

import math
from itertools import pairwise
from pathlib import Path
from typing import Any

from .config import Settings
from .motion_library import read_json, sha256
from .video_editing_contracts import SemanticBeat, Transcript

PICTURE_GROUP = "HY-A3"
PICTURE_PROFILE = "picture-parallel-3"
HY_PICTURE_TEMPLATE_ID = "hypit-picture-scenes-v1"
PICTURE_FPS = 30
PICTURE_PATHS = [f"/items/{i}/path" for i in range(3)]
ENTRY_PATHS = [f"/items/{i}/entry_frame" for i in range(3)]
PICTURE_TRACKS = ("/background/path", "/presenter/path")
PICTURE_CAPTION_BASELINE = 1060
_STAGGER_RENDERER_SHA256 = (
    "306f69356e311ff971f94a5458c3d2e0eb3b0ffd7716a7a9c7987a8c027dddd4"
)
NATIVE_FILES = {
    "commercial_runtime/picture_parallel.py": (
        "5fcbbc8c825bbb91563aeeb4713fb7ee128e20538184605b35fd44fcf3cfd6a7"
    ),
    "commercial_runtime/special.py": (
        "aac975ae441d6377fbc1063a0900cf5808d3317f6e50765dd34e0d2d65f017ee"
    ),
}
CLI_SHA256 = "1d962a229df2429fca2364e16a718b22ab0032851ed33e230ad68589eeb52f81"


def audit_picture_entry(package: Path, group: dict) -> None:
    renderer = (package / group["entry"]).parent / "packages/stagger/dist/render.js"
    if sha256(renderer) != _STAGGER_RENDERER_SHA256:
        raise ValueError("Original Hypit picture arrival changed")


def automatic_picture_config() -> dict[str, Any]:
    """Use the existing three-picture schema and the verified portrait layout."""
    return {
        "profile": PICTURE_PROFILE,
        "width": 360,
        "height": 640,
        "fps": PICTURE_FPS,
        "frames": None,
        "font": "pkg://assets/fonts/Noto_Sans_SC_Medium--9c62ceb174d7.otf",
        "background": {
            "path": None,
            "start_seconds": None,
            "blur_sigma": 12,
            "brightness": -0.18,
            "saturation": 0.65,
        },
        "presenter": {
            "path": None,
            "start_seconds": None,
            "rect": [0.22, 0.025, 0.56, 0.463],
        },
        "items": [
            {
                "path": None,
                "rect": [x, 320, 102, 150],
                "entry_frame": None,
                "rotation_deg": 0,
                "direction": "top",
            }
            for x in (18, 129, 240)
        ],
        "enter_frames": 10,
        "radius_px": 10,
        "border_px": 1,
        "border_color": "#e6e9ef",
        "image_fit": "contain",
    }


def picture_entry_frame(config: dict, path: str) -> int:
    item = config["items"][ENTRY_PATHS.index(path)]
    if (
        config.get("profile") != PICTURE_PROFILE
        or config.get("fps") != PICTURE_FPS
        or config.get("enter_frames") != 10
        or item["direction"] != "top"
        or item["rect"][3] != 150
    ):
        raise ValueError("Picture cues require the verified top-entry geometry")
    # Original easeOut moves a 198px offset to 160.38px at frame one,
    # outside the 150px clip. Frame two reaches 126.72px and draws ink.
    return item["entry_frame"] + 2


def requires_hypit(semantic: dict[str, Any]) -> bool:
    return any(beat["group_id"].startswith("HY-A") for beat in semantic["beats"])


def internal_hypit_available(settings: Settings, workspace_id: str | None) -> bool:
    return bool(
        settings.environment in {"development", "test"}
        and settings.auth_mode == "development"
        and workspace_id
        and workspace_id == settings.video_editing_hypit_internal_workspace
        and settings.video_editing_hypit_local_module
        and settings.video_editing_hypit_local_module.is_file()
        and settings.video_editing_hypit_local_chrome
        and settings.video_editing_hypit_local_chrome.is_file()
    )


def hypit_tools(settings: Settings, workspace_id: str | None) -> dict[str, str]:
    if not internal_hypit_available(settings, workspace_id):
        raise ValueError("Hypit requires the configured internal development workspace")
    module = settings.video_editing_hypit_local_module
    chrome = settings.video_editing_hypit_local_chrome
    assert module is not None and chrome is not None
    module = module.resolve()
    if (
        sha256(module) != CLI_SHA256
        or read_json(module.parent.parent / "package.json").get("version") != "0.2.12"
    ):
        raise ValueError("The audited Hypit CLI version or module bytes changed")
    return {"hypit_module": str(module), "chrome": str(chrome.resolve())}


def picture_fields(schema: dict) -> list[dict[str, Any]]:
    profile = next(
        row["properties"]
        for row in schema["oneOf"]
        if row.get("properties", {}).get("profile", {}).get("const") == PICTURE_PROFILE
    )
    fields: list[dict[str, Any]] = []

    def add(path: str, spec: dict, *, optional: bool = False) -> None:
        key = path.rsplit("/", 1)[-1]
        category = {
            "path": "resource",
            "entry_frame": "event",
            "font": "selected_bundled_font",
            "start_seconds": "hypit_source_start",
            "frames": "clock_owned_by_compiler",
            "fps": "clock_owned_by_compiler",
        }.get(key, "native_parameter")
        row = {
            "path": path,
            "category": category,
            "value_type": spec.get("type", "str"),
        }
        if category == "event":
            row["unit"] = "frames"
        if category == "resource":
            row["resource_kind"] = "media"
        if optional:
            row["optional_parent"] = "presenter"
        fields.append(row)

    for key, spec in profile.items():
        if key in {"background", "presenter"}:
            for child, value in spec["properties"].items():
                add(f"/{key}/{child}", value, optional=key == "presenter")
        elif key == "items":
            for i in range(len(PICTURE_PATHS)):
                for child, value in spec["items"]["properties"].items():
                    add(f"/items/{i}/{child}", value)
        else:
            add(f"/{key}", spec)
    return fields


def compile_picture_clocks(
    package: Path,
    config: dict,
    native: dict,
    assets: dict[str, dict[str, Any]],
    transcript: Transcript,
    beat: SemanticBeat,
) -> tuple[dict[str, float], list[dict]]:
    if any(sha256(package / path) != digest for path, digest in NATIVE_FILES.items()):
        raise ValueError("Audited original Hypit media sampling changed")
    clock = native["clock"]
    start_ms, end_ms = clock["start_ms"], clock["end_ms"]
    frames = math.ceil((end_ms - start_ms) / 1000 * PICTURE_FPS)
    source_end = start_ms / 1000 + frames / PICTURE_FPS
    if (
        not 0 <= start_ms < end_ms <= transcript.duration_ms
        or source_end > transcript.duration_ms / 1000 + 0.001
    ):
        raise ValueError("Rounded Hypit window leaves the actual recorded source")
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    tracks = ["background", "presenter"] if "presenter" in config else ["background"]
    if set(media) != {*PICTURE_PATHS, *(f"/{track}/path" for track in tracks)}:
        raise ValueError("Hypit needs the current source and three image bindings")
    pictures = [assets[media[path]] for path in PICTURE_PATHS]
    if (
        any(
            row.get("kind") != "image" or row.get("source") != "project_upload"
            for row in pictures
        )
        or len({row["sha256"] for row in pictures}) != 3
    ):
        raise ValueError("Hypit requires three distinct current project image bytes")
    events = {row["path"]: row["value"] for row in native["events"]}
    if set(events) != set(ENTRY_PATHS):
        raise ValueError("Every Hypit picture entry needs a measured word anchor")
    anchors = {event.path: event for event in beat.native_events}
    if (
        beat.relation != "parallel"
        or len(beat.relation_items) != 3
        or any(
            item.native_media_paths != [media_path]
            or item.asset_ids != [media[media_path]]
            or anchors[event_path].token_id != item.first_token_id
            or anchors[event_path].edge != "start"
            for item, media_path, event_path in zip(
                beat.relation_items, PICTURE_PATHS, ENTRY_PATHS, strict=True
            )
        )
    ):
        raise ValueError(
            "Bind each Hypit picture and arrival to its own spoken relation item"
        )
    entries = [events[path] for path in ENTRY_PATHS]
    enter = config["enter_frames"]
    if (
        type(enter) is not int
        or enter < 1
        or any(a >= b for a, b in pairwise(entries))
        or entries[-1] + enter >= frames
    ):
        raise ValueError(
            "Hypit picture entries must be ordered and leave a reading interval"
        )
    assigned, receipts = {}, []
    for track in tracks:
        path = f"/{track}/path"
        asset = assets[media[path]]
        if (
            asset.get("kind") != "original_video"
            or asset.get("sha256") != transcript.source_sha256
        ):
            raise ValueError("Hypit moving tracks must use this recorded source")
        start_path = f"/{track}/start_seconds"
        assigned[start_path] = start_ms / 1000
        receipts.append(
            {
                "media_path": path,
                "asset_id": media[path],
                "source_sha256": transcript.source_sha256,
                "policy": "transcript_source_window",
                "source_start_ms": start_ms,
                "source_end_ms": round(source_end * 1000, 6),
                "source_start_path": start_path,
                "native_source_files": NATIVE_FILES,
                "profile_id": PICTURE_PROFILE,
                "native_sampling_expression": (
                    "ffmpeg -ss start_seconds -t frames/fps, then local media clock"
                ),
                "timing_review": "unreviewed",
            }
        )
    return assigned, receipts
