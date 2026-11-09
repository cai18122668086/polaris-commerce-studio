"""Bind current editorial sound choices to the original episode protocol."""

import math
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .motion_library import inside, read_json, sha256
from .video_editing_contracts import Transcript
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


def compile_sound(
    package: Path,
    transcript: Transcript,
    episode: dict,
    design: NativeSoundDesign,
    event_bindings: dict[tuple[str, str], tuple[int, dict]],
    choice_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compile trusted sound choices without copying an old timeline."""
    duration = episode["source"]["duration_seconds"]
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
    for cue in design.fx:
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
        config_path: list[str | int] = []
        value = shot["config"]
        for part in cue.event_path[1:].split("/"):
            field = part.replace("~1", "/").replace("~0", "~")
            segment = int(field) if isinstance(value, list) else field
            config_path.append(segment)
            value = value[segment]
        if value != binding["value"]:
            raise ValueError("FX anchor differs from the compiled native event")
        fps = shot["config"].get("fps", 30)
        seconds = shot["start_seconds"] + (value / fps if unit == "frames" else value)
        if (
            not shot["start_seconds"] <= seconds < shot["end_seconds"]
            or seconds + cue.trim_duration_seconds > duration + 0.0001
            or abs(seconds - binding["measured_anchor_ms"] / 1000)
            > 1 / episode["output"]["fps"]
        ):
            raise ValueError("FX anchor or tail exceeds its current timing")
        event = cue.model_dump(mode="json", exclude={"beat_id", "event_path"})
        event.update(
            anchor_seconds=seconds,
            anchor_ref={
                "shot_index": shot_index,
                "config_path": config_path,
                "unit": unit,
            },
        )
        fx.append(event)
        cue_evidence.append(
            {
                **event,
                "asset_sha256": row["sha256"],
                "word_binding": binding,
                "beat_id": cue.beat_id,
                "group_id": shot["group_id"],
            }
        )

    for track in design.music:
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
        music.append(event)
        music_evidence.append(
            {**event, "asset_sha256": row["sha256"], "loop_allowed": track.loop}
        )
    episode.update(fx=fx, music=music, mix={"voice_gain_db": design.voice_gain_db})
    return {
        "fx": cue_evidence,
        "music": music_evidence,
        "voice_gain_db": design.voice_gain_db,
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
    for cue, actual in zip(plan["fx"], rendered, strict=True):
        anchor = actual["anchor_basis"]
        onset_delta = actual["effective_onset_seconds"] - cue["anchor_seconds"]
        if (
            actual["asset_id"] != cue["asset_id"]
            or actual["source_sha256"] != cue["asset_sha256"]
            or anchor["kind"] != "native_event"
            or anchor["shot_index"] != cue["anchor_ref"]["shot_index"]
            or anchor["config_path"] != cue["anchor_ref"]["config_path"]
            or anchor["unit"] != cue["anchor_ref"]["unit"]
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
            }
        )
    stems = {}
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
