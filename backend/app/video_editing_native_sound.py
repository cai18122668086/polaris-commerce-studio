"""Bind current editorial sound choices to the original episode protocol."""

import math
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .motion_library import inside, read_json, sha256
from .video_editing_azl_panels import AZL_ENTRY, AZL_GROUPS, azl_output_bounds
from .video_editing_browser_rotation import (
    ROTATION_EVENTS,
    ROTATION_GROUP,
    rotation_entry_frame,
)
from .video_editing_contracts import NativeRenderEdits, Transcript
from .video_editing_cxbr import CXBR_SOUNDS, cxbr_entry_frame
from .video_editing_hypit_strips import verify_stagger_entry
from .video_editing_judgment import (
    JUDGMENT_EVENTS,
    JUDGMENT_GROUP,
    judgment_entry_frame,
)
from .video_editing_native_content import PACKAGE_GROUP
from .video_editing_presenter_motion import (
    MOTION_COMPOSITOR_SHA256,
    PRESENTER_MOTION_GROUPS,
    motion_entry_frame,
)
from .video_editing_question_branch import (
    QUESTION_BRANCH,
    QUESTION_ENTRY,
    QUESTION_GROUP,
    question_overlay_entry_frame,
)
from .video_editing_question_card import (
    QUESTION_CARD_ENTRANCES,
    question_card_a_shot,
    question_card_entry_frame,
)
from .video_editing_render_edits import MUSIC_REDUCTION_DB
from .video_editing_subtitle_sound_clock import (
    SUBTITLE_ENTRY_SYNC,
    subtitle_entry_clock,
)
from .video_editing_yy6_scenes import YY6_SOUND_EVENTS
from .video_editing_yy_openings import (
    YY_OPENING_COMPOSITOR_SHA256,
    YY_OPENING_ENTRY_EVENTS,
    yy_opening_entry_frame,
)
from .video_studio_schemas import StrictVideoModel


class WordBoundary(StrictVideoModel):
    token_id: str = Field(min_length=1, max_length=120)
    edge: Literal["start", "end"]


SoundBoundary = WordBoundary | Literal["episode_start", "episode_end"]


class NativeSoundCue(StrictVideoModel):
    asset_id: str = Field(min_length=1, max_length=128)
    beat_id: str = Field(min_length=1, max_length=120)
    event_path: str = Field(min_length=2, max_length=200)
    phase: Literal["entry", "settle", "exit", "handoff"]
    purpose: str = Field(min_length=1, max_length=1000)
    source_start_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    trim_duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    target_peak_dbfs: float = Field(ge=-60, le=0, allow_inf_nan=False)
    pan: float = Field(default=0, ge=-1, le=1, allow_inf_nan=False)
    onset_policy: Literal["measured", "preserve"] = "measured"
    onset_reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def check_intent(self) -> Self:
        if not self.purpose.strip() or (
            self.onset_policy == "preserve" and not self.onset_reason.strip()
        ):
            raise ValueError(
                "Current sound purpose and intentional lead-in reason required"
            )
        return self


class MusicLevel(StrictVideoModel):
    at: SoundBoundary
    gain_db: float = Field(ge=-60, le=0, allow_inf_nan=False)


class NativeMusicTrack(StrictVideoModel):
    asset_id: str = Field(min_length=1, max_length=128)
    start: SoundBoundary
    end: SoundBoundary
    source_start_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    gain_db: float = Field(ge=-60, le=0, allow_inf_nan=False)
    fade_seconds: float = Field(ge=0, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=1000)
    loop: bool = False
    envelope: list[MusicLevel] = Field(default_factory=list, max_length=24)


class NativeSoundDesign(StrictVideoModel):
    fx: list[NativeSoundCue] = Field(default_factory=list, max_length=120)
    music: list[NativeMusicTrack] = Field(default_factory=list, max_length=8)
    voice_gain_db: float = Field(default=0, ge=-18, le=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_selection(self) -> Self:
        if not self.fx and not self.music:
            raise ValueError("Select an original sound cue or music track for this mix")
        return self


def package_entry_frame(shot: dict, fps: int, event_path: str) -> int:
    if (
        shot["group_id"] != PACKAGE_GROUP
        or shot["layer"] != "scene"
        or fps != 30
        or event_path not in {f"/timing/events/item{i}" for i in range(4)}
    ):
        raise ValueError("Package sound needs an original scene entry at 30 fps")
    event = event_path.rsplit("/", 1)[1]
    start_ms = round(shot["start_seconds"] * 1000)
    local_ms = round(shot["config"]["timing"]["events"][event] * 1000)
    # Native package easing is zero at its exact event. The compositor
    # truncates the positive fractional shot origin in the output timebase.
    return start_ms * fps // 1000 + local_ms * fps // 1000 + 1


def compile_sound(
    package: Path,
    transcript: Transcript,
    episode: dict,
    design: NativeSoundDesign,
    event_bindings: dict[tuple[str, str], tuple[int, dict]],
    choice_snapshot: dict[str, Any] | None,
    edits: NativeRenderEdits | None = None,
    *,
    sync_subtitle_entries: bool = False,
    sync_yy_opening_entries: bool = False,
    sync_presenter_motion_entries: bool = False,
    sync_azl_entries: bool = False,
    sync_cxbr_entries: bool = False,
) -> dict[str, Any]:
    """Compile trusted sound choices without copying an old timeline."""
    duration = episode["source"]["duration_seconds"]
    if sync_yy_opening_entries and (
        sha256(package / "commercial_runtime/episode.py")
        != YY_OPENING_COMPOSITOR_SHA256
    ):
        raise ValueError("Original scene compositor clock changed")
    if (sync_presenter_motion_entries or sync_cxbr_entries) and (
        sha256(package / "commercial_runtime/episode.py") != MOTION_COMPOSITOR_SHA256
    ):
        raise ValueError("Original motion compositor clock changed")
    tokens = {token.id: token for token in transcript.tokens}
    stock = {
        item["id"]: item
        for item in read_json(package / "asset-manifest.json")["assets"]
    }
    runtime_fx = {
        item["id"]: item
        for item in read_json(package / "assets/sfx/runtime-assets.json")["assets"]
    }
    avoided = {
        row["target_id"]
        for row in (choice_snapshot or {}).get("notes", [])
        if row["target_kind"] == "bundled_asset" and row["choice"] == "avoid"
    }

    def asset(asset_id: str, kinds: set[str]) -> dict:
        row = stock[asset_id]
        if (
            asset_id in avoided
            or row["kind"] not in kinds
            or sha256(inside(package, row["path"])) != row["sha256"]
        ):
            raise ValueError(
                "Original audio asset does not match the current selection"
            )
        return row

    def boundary(point: SoundBoundary) -> float:
        if isinstance(point, WordBoundary):
            token = tokens[point.token_id]
            return (token.start_ms if point.edge == "start" else token.end_ms) / 1000
        return 0 if point == "episode_start" else duration

    fx, music, cue_evidence, music_evidence = [], [], [], []
    used_events = set()
    excluded_beats = set(edits.source_only_beat_ids) if edits else set()
    removed_cues = []
    for cue in design.fx:
        if cue.beat_id in excluded_beats:
            removed_cues.append(
                {
                    "beat_id": cue.beat_id,
                    "asset_id": cue.asset_id,
                    "event_path": cue.event_path,
                }
            )
            continue
        row = asset(cue.asset_id, {"sfx", "sfx-processed"})
        runtime = runtime_fx[cue.asset_id]
        if (
            runtime["sha256"] != row["sha256"]
            or inside(package / "assets/sfx", runtime["path"])
            != inside(package, row["path"])
            or cue.source_start_seconds + cue.trim_duration_seconds
            > runtime["duration_seconds"] + 0.0001
        ):
            raise ValueError("FX slice does not fit the original runtime asset")
        key = (cue.beat_id, cue.event_path)
        if key in used_events:
            raise ValueError("A native action already has an FX cue")
        used_events.add(key)
        shot_index, binding = event_bindings[key]
        shot = episode["shots"][shot_index]
        unit = binding["unit"]
        hypit_entry = binding.get("hypit_entry")
        native_ref = {}
        if hypit_entry:
            if (
                cue.phase != "entry"
                or unit != "frames"
                or hypit_entry["group_id"] != shot["group_id"]
                or episode["output"]["fps"] != 30
            ):
                raise ValueError("Hypit sound cue needs a current label entrance")
            value = hypit_entry["frame"]
        else:
            config_path: list[str | int] = []
            value = shot["config"]
            for part in cue.event_path[1:].split("/"):
                field = part.replace("~1", "/").replace("~0", "~")
                segment = int(field) if isinstance(value, list) else field
                config_path.append(segment)
                value = value[segment]
            native_ref["anchor_ref"] = {
                "shot_index": shot_index,
                "config_path": config_path,
                "unit": unit,
            }
        if value != binding["value"]:
            raise ValueError("FX anchor differs from the compiled native event")
        fps = shot["config"].get("fps", 30)
        entry_seconds = shot["start_seconds"] + (
            value / fps if unit == "frames" else value
        )
        seconds = entry_seconds
        question_entry = package_entry = rotation_entry = judgment_entry = None
        question_card_entry = yy_opening_entry = presenter_motion_entry = azl_entry = (
            cxbr_entry
        ) = None
        if (
            sync_azl_entries
            and shot["group_id"] in AZL_GROUPS
            and cue.phase == "entry"
            and cue.event_path == AZL_ENTRY
        ):
            fps = episode["output"]["fps"]
            frame, _ = azl_output_bounds(shot, fps)
            seconds = frame / fps
            native_ref = {}
            azl_entry = {"shot_index": shot_index, "output_frame": frame}
        if (
            sync_cxbr_entries
            and cue.phase == "entry"
            and cue.event_path in CXBR_SOUNDS.get(shot["group_id"], {})
        ):
            fps = episode["output"]["fps"]
            frame = cxbr_entry_frame(shot, fps, cue.event_path)
            seconds = frame / fps
            native_ref = {}
            cxbr_entry = {"shot_index": shot_index, "output_frame": frame}
        if (
            sync_presenter_motion_entries
            and shot["group_id"] in PRESENTER_MOTION_GROUPS
            and cue.phase == "entry"
        ):
            fps = episode["output"]["fps"]
            frame = motion_entry_frame(shot, fps, cue.event_path)
            seconds = frame / fps
            native_ref = {}
            presenter_motion_entry = {"shot_index": shot_index, "output_frame": frame}
        if (
            sync_yy_opening_entries
            and shot["group_id"] in YY_OPENING_ENTRY_EVENTS
            and (
                cue.event_path == YY_OPENING_ENTRY_EVENTS[shot["group_id"]]
                or cue.event_path in YY6_SOUND_EVENTS.get(shot["group_id"], {})
            )
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = yy_opening_entry_frame(shot, output_fps, cue.event_path)
            seconds = frame / output_fps
            native_ref = {}
            yy_opening_entry = {"shot_index": shot_index, "output_frame": frame}
        if (
            question_card_a_shot(shot)
            and cue.event_path in QUESTION_CARD_ENTRANCES
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = question_card_entry_frame(shot, output_fps, cue.event_path)
            seconds = frame / output_fps
            native_ref = {}
            question_card_entry = {
                "shot_index": shot_index,
                "output_frame": frame,
                "event_path": cue.event_path,
            }
        if (
            shot["group_id"] == QUESTION_GROUP
            and shot["layer"] in {"overlay", "scene"}
            and shot["config"].get("branch") == QUESTION_BRANCH
            and cue.event_path == QUESTION_ENTRY
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = question_overlay_entry_frame(shot, output_fps)
            seconds = frame / output_fps
            native_ref = {}
            question_entry = {"shot_index": shot_index, "output_frame": frame}
        if (
            shot["group_id"] == PACKAGE_GROUP
            and shot["config"]["media"]["presenter"]["kind"] == "video"
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = package_entry_frame(shot, output_fps, cue.event_path)
            seconds = frame / output_fps
            native_ref = {}
            package_entry = {
                "shot_index": shot_index,
                "output_frame": frame,
                "event_path": cue.event_path,
            }
        if (
            shot["group_id"] == ROTATION_GROUP
            and cue.event_path in ROTATION_EVENTS
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = rotation_entry_frame(shot, output_fps, cue.event_path)
            seconds = frame / output_fps
            native_ref = {}
            rotation_entry = {
                "shot_index": shot_index,
                "output_frame": frame,
                "event_path": cue.event_path,
            }
        if (
            shot["group_id"] == JUDGMENT_GROUP
            and shot["config"]["content"].get("captions") == []
            and cue.event_path in JUDGMENT_EVENTS[:-1]
            and cue.phase == "entry"
        ):
            output_fps = episode["output"]["fps"]
            frame = judgment_entry_frame(shot, output_fps, cue.event_path)
            seconds = frame / output_fps
            native_ref = {}
            judgment_entry = {
                "shot_index": shot_index,
                "output_frame": frame,
                "event_path": cue.event_path,
            }
        if hypit_entry:
            # The original compositor applies setpts in the output frame time
            # base. Its positive fractional shot origin truncates to a frame.
            start_ms = round(shot["start_seconds"] * 1000)
            output_frame = start_ms * 30 // 1000 + hypit_entry["audible_frame"]
            hypit_entry = {**hypit_entry, "output_frame": output_frame}
            seconds = output_frame / 30
        if (
            not shot["start_seconds"] <= seconds < shot["end_seconds"]
            or seconds + cue.trim_duration_seconds > duration + 0.0001
            or abs(entry_seconds - binding["measured_anchor_ms"] / 1000)
            > 1 / episode["output"]["fps"]
        ):
            raise ValueError("FX anchor or tail exceeds its current timing")
        event = cue.model_dump(mode="json", exclude={"beat_id", "event_path"})
        event.update(anchor_seconds=seconds, **native_ref)
        fx.append(event)
        sync_entry = (
            sync_subtitle_entries
            and shot["layer"] == "subtitle"
            and cue.phase == "entry"
            and cue.onset_policy == "measured"
            and "anchor_ref" in native_ref
            and unit == "frames"
        )
        cue_evidence.append(
            {
                **event,
                "asset_sha256": row["sha256"],
                "word_binding": binding,
                "beat_id": cue.beat_id,
                "group_id": shot["group_id"],
                **({"hypit_entry": hypit_entry} if hypit_entry else {}),
                **({"question_entry": question_entry} if question_entry else {}),
                **(
                    {"question_card_entry": question_card_entry}
                    if question_card_entry
                    else {}
                ),
                **({"package_entry": package_entry} if package_entry else {}),
                **({"rotation_entry": rotation_entry} if rotation_entry else {}),
                **({"judgment_entry": judgment_entry} if judgment_entry else {}),
                **({"yy_opening_entry": yy_opening_entry} if yy_opening_entry else {}),
                **({"azl_entry": azl_entry} if azl_entry else {}),
                **({"cxbr_entry": cxbr_entry} if cxbr_entry else {}),
                **(
                    {"presenter_motion_entry": presenter_motion_entry}
                    if presenter_motion_entry
                    else {}
                ),
                **({"subtitle_entry_sync": SUBTITLE_ENTRY_SYNC} if sync_entry else {}),
            }
        )

    music_choice = edits.music if edits else None
    for track in design.music if music_choice != "off" else []:
        row = asset(track.asset_id, {"music"})
        start, end = boundary(track.start), boundary(track.end)
        length = end - start
        if (
            not 0 <= start < end <= duration
            or not track.reason.strip()
            or track.fade_seconds > length / 2
            or track.source_start_seconds >= row["duration_seconds"]
            or (
                not track.loop
                and track.source_start_seconds + length
                > row["duration_seconds"] + 0.0001
            )
        ):
            raise ValueError("Music range, fade or source selection is invalid")
        envelope = []
        prior = -1.0
        for point in track.envelope:
            at = round(boundary(point.at) - start, 6)
            if not 0 <= at <= round(length, 6) or at <= prior:
                raise ValueError("Music levels must follow the current track clock")
            envelope.append({"seconds": at, "gain_db": point.gain_db})
            prior = at
        event = {
            **track.model_dump(
                mode="json", exclude={"start", "end", "loop", "envelope"}
            ),
            "start_seconds": start,
            "end_seconds": end,
            "envelope": envelope,
        }
        if music_choice == "lower":
            event["gain_db"] = track.gain_db - MUSIC_REDUCTION_DB
        music.append(event)
        music_evidence.append(
            {
                **event,
                "asset_sha256": row["sha256"],
                "loop_allowed": track.loop,
                **(
                    {"original_gain_db": track.gain_db}
                    if music_choice == "lower"
                    else {}
                ),
            }
        )
    episode.update(fx=fx, music=music, mix={"voice_gain_db": design.voice_gain_db})
    return {
        "fx": cue_evidence,
        "music": music_evidence,
        "voice_gain_db": design.voice_gain_db,
        **({"removed_segment_cues": removed_cues} if removed_cues else {}),
        **(
            {
                "music_edit": {
                    "mode": music_choice,
                    "original_track_ids": [track.asset_id for track in design.music],
                }
            }
            if music_choice
            else {}
        ),
    }


def verify_rendered_sound(root: Path, native: dict, plan: dict) -> dict:
    """Check native sound artifacts and return path-free delivery evidence."""
    signal = native["audio_signal"]
    if (
        not signal["finite"]
        or signal["overload"]
        or not math.isfinite(signal["peak_dbfs"])
    ):
        raise ValueError("Native mix signal failed validation")
    rendered = native["fx_receipt"]["events"]
    if len(rendered) != len(plan["fx"]):
        raise ValueError("Native FX count differs from the compiled plan")
    events = []
    episode = None
    for cue, actual in zip(plan["fx"], rendered, strict=True):
        anchor = actual["anchor_basis"]
        subtitle_entry = None
        if cue.get("subtitle_entry_sync"):
            if episode is None:
                episode = read_json(root / "episode.json")
            subtitle_entry = subtitle_entry_clock(root, episode, cue, native["shots"])
            if subtitle_entry["aligned_to_frame"]:
                cue = {
                    **cue,
                    "word_anchor_seconds": cue["anchor_seconds"],
                    "anchor_seconds": subtitle_entry["output_frame"]
                    / episode["output"]["fps"],
                }
        onset_delta = actual["effective_onset_seconds"] - cue["anchor_seconds"]
        if subtitle_entry and subtitle_entry["aligned_to_frame"]:
            anchor_valid = anchor["kind"] == "explicit_current_clock"
        elif hypit_entry := cue.get("hypit_entry"):
            verify_stagger_entry(root, hypit_entry)
            anchor_valid = anchor["kind"] == "explicit_current_clock"
        elif question_entry := cue.get("question_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][question_entry["shot_index"]]
            frame = question_overlay_entry_frame(shot, fps)
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and question_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif question_card_entry := cue.get("question_card_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][question_card_entry["shot_index"]]
            path = question_card_entry["event_path"]
            frame = question_card_entry_frame(shot, fps, path)
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and path == cue["word_binding"]["path"]
                and question_card_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif package_entry := cue.get("package_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][package_entry["shot_index"]]
            frame = package_entry_frame(shot, fps, package_entry["event_path"])
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and package_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif rotation_entry := cue.get("rotation_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][rotation_entry["shot_index"]]
            frame = rotation_entry_frame(shot, fps, rotation_entry["event_path"])
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and rotation_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif judgment_entry := cue.get("judgment_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][judgment_entry["shot_index"]]
            path = judgment_entry["event_path"]
            frame = judgment_entry_frame(shot, fps, path)
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and shot["config"]["content"].get("captions") == []
                and path == cue["word_binding"]["path"]
                and judgment_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif yy_entry := cue.get("yy_opening_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][yy_entry["shot_index"]]
            path = cue["word_binding"]["path"]
            frame = yy_opening_entry_frame(shot, fps, path)
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and (
                    path == YY_OPENING_ENTRY_EVENTS[shot["group_id"]]
                    or path in YY6_SOUND_EVENTS.get(shot["group_id"], {})
                )
                and yy_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif motion_entry := cue.get("presenter_motion_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][motion_entry["shot_index"]]
            frame = motion_entry_frame(shot, fps, cue["word_binding"]["path"])
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and motion_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif panel_entry := cue.get("azl_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][panel_entry["shot_index"]]
            frame, _ = azl_output_bounds(shot, fps)
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and cue["word_binding"]["path"] == AZL_ENTRY
                and panel_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        elif cxbr_entry := cue.get("cxbr_entry"):
            if episode is None:
                episode = read_json(root / "episode.json")
            fps = episode["output"]["fps"]
            shot = episode["shots"][cxbr_entry["shot_index"]]
            frame = cxbr_entry_frame(shot, fps, cue["word_binding"]["path"])
            anchor_valid = (
                anchor["kind"] == "explicit_current_clock"
                and cxbr_entry["output_frame"] == frame
                and cue["anchor_seconds"] == frame / fps
            )
        else:
            ref = cue["anchor_ref"]
            anchor_valid = anchor["kind"] == "native_event" and all(
                anchor[key] == ref[key] for key in ("shot_index", "config_path", "unit")
            )
        if (
            actual["asset_id"] != cue["asset_id"]
            or actual["source_sha256"] != cue["asset_sha256"]
            or not anchor_valid
            or abs(actual["anchor_seconds"] - cue["anchor_seconds"]) > 1 / 48000
            or not math.isfinite(onset_delta)
            or (
                cue["onset_policy"] == "measured"
                and not -1 / 48000 <= onset_delta <= 0.005
            )
        ):
            raise ValueError("Native FX binding or measured onset changed")
        processed = (root / f"audio/fx-cues/{actual['index']:04}.wav").resolve()
        if (
            not processed.is_relative_to(root.resolve())
            or sha256(processed) != actual["processed_sha256"]
        ):
            raise ValueError("Native processed FX bytes changed")
        events.append(
            {
                **cue,
                "effective_onset_seconds": actual["effective_onset_seconds"],
                "lead_removed_seconds": actual["lead_removed_seconds"],
                "processed_sha256": actual["processed_sha256"],
                **({"subtitle_entry": subtitle_entry} if subtitle_entry else {}),
            }
        )
    stems = {}
    if not plan["music"] and (root / "audio/bgm.wav").exists():
        raise ValueError("Unplanned native BGM stem exists")
    for name in ("voice", "fx", "bgm") if plan["music"] else ("voice", "fx"):
        stem = inside(root, f"audio/{name}.wav")
        if stem.stat().st_size <= 44:
            raise ValueError("Native audio stem is empty")
        stems[name] = sha256(stem)
    if stems["fx"] != native["fx_receipt"]["sha256"]:
        raise ValueError("Native FX stem bytes changed")
    return {
        **plan,
        "fx": events,
        "stems_sha256": stems,
        "encoded_audio_signal": signal,
        "listening_review": "unreviewed",
    }
