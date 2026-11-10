"""Deterministic media/word-clock adapter around the preserved episode exporter."""

from __future__ import annotations

import copy
import difflib
import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from struct import iter_unpack
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from .config import Settings
from .motion_library import atomic_json, read_json, sha256
from .video_editing_azl_panels import AZL_LAYOUT_INTENT, verify_azl_layout
from .video_editing_caption_layout import (
    layout_main_captions,
    verify_native_caption_layout,
)
from .video_editing_captioning import (
    CaptionFailure,
    measured_caption_rows,
    segmentation_metadata,
    write_caption_receipt,
)
from .video_editing_contracts import Transcript, TranscriptToken, TranscriptUtterance
from .video_editing_cxbr import CXBR_CAPTION_INTENT, verify_cxbr_captions
from .video_editing_hypit_strips import HYPIT_SIDECAR_GROUPS
from .video_editing_native_layout import verify_inset_layout
from .video_editing_native_sound import verify_rendered_sound
from .video_editing_unified_scenes import (
    UNIFIED_CAPTION_INTENT,
    verify_unified_captions,
)
from .video_editing_yy_openings import (
    YY_OPENING_CAPTION_INTENT,
    verify_yy_opening_captions,
)

_MASTER_MAX_WIDTH = 1080
_MASTER_MAX_HEIGHT = 1920


class EditingFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def environment(settings: Settings) -> dict[str, str]:
    # The native subprocess gets no application/provider credentials.
    keep = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "LOCALAPPDATA",
        "USERPROFILE",
        "HOME",
        "TEMP",
        "TMP",
        "PATH",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    tool_dirs = [
        str(Path(p).resolve().parent)
        for p in (settings.video_editing_ffmpeg, settings.video_editing_ffprobe)
        if Path(p).is_file()
    ]
    env["PATH"] = os.pathsep.join([*tool_dirs, env.get("PATH", "")])
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    return env


def run(
    arguments: list[str],
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
    name: str,
) -> Path:
    """Fixed argv only; never evaluate shell, model output or arbitrary code."""
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    output = logs / (name + "-" + uuid4().hex[:8] + ".log")
    started = time.monotonic()
    with output.open("wb") as log:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment(settings),
            cwd=root,
            creationflags=creation_flags(),
            start_new_session=sys.platform != "win32",
        )
        try:
            while process.poll() is None:
                guard()
                if (
                    time.monotonic() - started
                    > settings.video_editing_subprocess_timeout
                ):
                    raise EditingFailure("EDITING_PROCESS_TIMEOUT")
                time.sleep(0.25)
            if process.returncode:
                raise EditingFailure("EDITING_" + name.upper() + "_FAILED")
        except BaseException:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                import signal

                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    return output


def probe(
    path: Path, settings: Settings, *, formats: str = "mov,matroska,webm"
) -> dict[str, Any]:
    result = subprocess.run(
        [
            settings.video_editing_ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            formats,
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        timeout=30,
        env=environment(settings),
        check=True,
    )
    return json.loads(result.stdout)


_MAX_SILENT_TAIL_SECONDS = 0.5
_MAX_SILENT_TAIL_PCM16_PEAK = 4  # About -78 dBFS; permits codec residue only.
ASR_TIMESTAMP_TOLERANCE_MS = 30


def _verified_silent_tail(
    target: Path,
    duration: float,
    video: dict,
    audio: dict,
    offset: float,
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
) -> dict | None:
    try:
        video_duration = float(video["duration"])
        frame_interval = float(1 / Fraction(video["avg_frame_rate"]))
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        # Containers without a separately measured video duration keep their
        # existing clock. In particular, do not infer one from the audio.
        return None
    gap = duration - video_duration
    if (
        not math.isfinite(video_duration)
        or not math.isfinite(frame_interval)
        or frame_interval <= 0
        or gap <= frame_interval + 0.001
    ):
        return None
    error = "EDITING_SOURCE_AUDIO_TAIL_REVIEW_REQUIRED"
    if video_duration < 0.5 or gap > _MAX_SILENT_TAIL_SECONDS:
        raise EditingFailure(error)
    try:
        sample_rate, channels = int(audio["sample_rate"]), int(audio["channels"])
    except (KeyError, TypeError, ValueError):
        raise EditingFailure(error) from None
    if not 8000 <= sample_rate <= 192000 or not 1 <= channels <= 8:
        raise EditingFailure(error)
    end_ms = math.floor(video_duration * 1000)
    cutoff = end_ms / 1000 - offset
    # Inspect every channel, since stereo can cancel in the recognition downmix.
    with TemporaryDirectory(prefix="tail-", dir=target.parent) as work:
        decoded = Path(work) / "audio.s16le"
        run(
            [
                settings.video_editing_ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "mov,matroska,webm",
                "-i",
                str(target),
                "-map",
                "0:a:0",
                "-vn",
                "-af",
                f"asetpts=PTS-STARTPTS,atrim=start={cutoff:.6f},asetpts=PTS-STARTPTS",
                "-t",
                "1",
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                str(decoded),
            ],
            root,
            settings,
            guard,
            "inspect_audio_tail",
        )
        samples = decoded.read_bytes()
    bytes_per_frame = 2 * channels
    if len(samples) % bytes_per_frame or len(samples) >= sample_rate * bytes_per_frame:
        raise EditingFailure(error)
    peak = max((abs(value) for (value,) in iter_unpack("<h", samples)), default=0)
    if peak > _MAX_SILENT_TAIL_PCM16_PEAK:
        raise EditingFailure(error)
    return {
        "container_end_ms": round(duration * 1000),
        "video_end_ms": end_ms,
        "audio_tail_frames": len(samples) // bytes_per_frame,
        "sample_rate": sample_rate,
        "channels": channels,
        "pcm16_peak": peak,
    }


def word_timestamp_end_limit(prepared: dict) -> int:
    # The analysis file retains the original audio even when the render clock
    # ends at the picture boundary of a verified silent tail.
    tail = prepared["clock"].get("silent_tail")
    end = prepared["duration_ms"] if tail is None else tail["analysis_audio_end_ms"]
    return end + ASR_TIMESTAMP_TOLERANCE_MS


def prepare(
    source: Path,
    expected: str,
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
) -> dict[str, Any]:

    target = root / "input" / "source.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".part")
        with source.open("rb") as incoming, temporary.open("wb") as output:
            while block := incoming.read(1024 * 1024):
                guard()
                output.write(block)
        if sha256(temporary) != expected:
            raise EditingFailure("EDITING_SOURCE_CHANGED")
        temporary.replace(target)
    elif sha256(target) != expected:
        raise EditingFailure("EDITING_SOURCE_CHANGED")
    info = probe(target, settings)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not video or not audio:
        raise EditingFailure("EDITING_SPEECH_AUDIO_REQUIRED")
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or not 0.5 <= duration <= 600:
        raise EditingFailure("EDITING_DURATION_UNSUPPORTED")
    video_start = float(video.get("start_time", 0))
    offset = float(audio.get("start_time", 0)) - video_start
    if not math.isfinite(offset) or abs(offset) > 0.02 or abs(video_start) > 0.02:
        raise EditingFailure("EDITING_CLOCK_REVIEW_REQUIRED")
    rotation = [s.get("rotation", 0) for s in video.get("side_data_list", [])]
    if any(rotation) or int(video.get("tags", {}).get("rotate", 0)):
        raise EditingFailure("EDITING_ROTATION_REVIEW_REQUIRED")
    silent_tail = _verified_silent_tail(
        target, duration, video, audio, offset, root, settings, guard
    )
    # Preserve the entire source audio, including tail and pauses, for analysis.
    audio_path = root / "input" / "speech.wav"
    if not audio_path.exists():
        run(
            [
                settings.video_editing_ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "mov,matroska,webm",
                "-i",
                str(target),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
            root,
            settings,
            guard,
            "extract_audio",
        )
    with wave.open(str(audio_path), "rb") as stream:
        analysis_audio_end_ms = round(
            stream.getnframes() * 1000 / stream.getframerate() + offset * 1000
        )
    if silent_tail is not None:
        silent_tail["analysis_audio_end_ms"] = analysis_audio_end_ms
    receipt = {
        "source_sha256": expected,
        "audio_sha256": sha256(audio_path),
        "duration_ms": silent_tail["video_end_ms"]
        if silent_tail
        else round(duration * 1000),
        "probe": info,
        "clock": {
            "policy": "original_video_audio",
            "audio_offset_ms": round(offset * 1000),
            "analysis_audio_end_ms": analysis_audio_end_ms,
            "speech_stretched": False,
            **({"silent_tail": silent_tail} if silent_tail is not None else {}),
        },
    }
    atomic_json(root / "prepared.json", receipt)
    return receipt


def transcribe(
    audio: Path,
    prepared: dict,
    settings: Settings,
    reference: str | None = None,
    language: str = "zh",
) -> Transcript:
    """An initial local ASR route; no paid call and no invented word timestamps."""
    if settings.video_editing_asr_provider == "funasr":
        if language not in {"zh", "auto"}:
            raise EditingFailure("EDITING_ASR_LANGUAGE_UNSUPPORTED")
        from .video_editing_funasr import transcribe_funasr

        return transcribe_funasr(
            audio,
            prepared,
            Path(settings.video_editing_asr_model).resolve(),
            settings.video_editing_asr_device,
            reference,
        )
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(
        settings.video_editing_asr_model,
        device=settings.video_editing_asr_device,
        compute_type="int8"
        if settings.video_editing_asr_device == "cpu"
        else "float16",
        cpu_threads=4,
        num_workers=1,
    )
    # No reference prompt: recognize what the recording actually says first.
    # Decode once with the configured FFmpeg; hand the measured PCM to ASR.
    with wave.open(str(audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (
            1,
            2,
            16000,
        ):
            raise EditingFailure("EDITING_ASR_AUDIO_FORMAT_INVALID")
        samples = (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(
                np.float32
            )
            / 32768
        )
    segments, info = model.transcribe(
        samples,
        language=None if language == "auto" else language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
    )
    tokens: list[TranscriptToken] = []
    utterances: list[TranscriptUtterance] = []
    offset = prepared["clock"]["audio_offset_ms"]
    duration = prepared["duration_ms"]
    end_limit = word_timestamp_end_limit(prepared)
    for segment in segments:
        ids = []
        for word in segment.words or []:
            start, end = (
                round(word.start * 1000) + offset,
                round(word.end * 1000) + offset,
            )
            if not word.word.strip():
                continue
            if not (0 <= start < duration and start < end <= end_limit):
                raise EditingFailure("EDITING_ASR_TIMING_INVALID")
            token = TranscriptToken(
                id=f"t{len(tokens):06}",
                text=word.word,
                start_ms=start,
                end_ms=min(end, duration),
                confidence=word.probability,
            )
            tokens.append(token)
            ids.append(token.id)
        if ids:
            selected = tokens[-len(ids) :]
            utterances.append(
                TranscriptUtterance(
                    id=f"u{len(utterances):05}",
                    text="".join(t.text for t in selected),
                    token_ids=ids,
                    start_ms=selected[0].start_ms,
                    end_ms=selected[-1].end_ms,
                )
            )
    if not tokens:
        raise EditingFailure("EDITING_NO_SPEECH_RECOGNIZED")

    matches_reference, differences = reference_differences(
        "".join(t.text for t in tokens), reference
    )
    return Transcript(
        audio_sha256=prepared["audio_sha256"],
        source_sha256=prepared["source_sha256"],
        duration_ms=prepared["duration_ms"],
        provider="faster-whisper",
        model=settings.video_editing_asr_model,
        language=info.language,
        tokens=tokens,
        utterances=utterances,
        reference_text=reference,
        reference_matches=matches_reference,
        differences=differences,
    )


def reference_differences(
    spoken: str, reference: str | None
) -> tuple[bool | None, list[dict]]:
    def clean(text: str) -> str:
        return re.sub(r"[^\w]", "", text).casefold()

    actual, expected = clean(spoken), clean(reference or "")
    differences = []
    if reference:
        for op, a, b, c, d in difflib.SequenceMatcher(
            None, expected, actual, autojunk=False
        ).get_opcodes():
            if op != "equal":
                differences.append(
                    {"operation": op, "reference": expected[a:b], "spoken": actual[c:d]}
                )
    return ((expected == actual) if reference else None), differences


def caption_rows(transcript: Transcript) -> list[dict[str, Any]]:
    try:
        return measured_caption_rows(transcript)
    except CaptionFailure as error:
        raise EditingFailure(error.code) from None


def layout_captions(plan: dict, captions: list[dict], settings: Settings) -> None:
    role = plan.get("typography", {}).get("caption")
    if (
        not isinstance(role, dict)
        or not {"font_id", "size_px", "max_width_px"} <= role.keys()
    ):
        raise EditingFailure("EDITING_CAPTION_LAYOUT_INVALID")
    if role["font_id"] != plan["design"]["caption_font_id"]:
        raise EditingFailure("EDITING_CAPTION_DESIGN_MISMATCH")
    try:
        rendered, report = layout_main_captions(
            settings.video_editing_library_dir,
            captions,
            plan["typography"]["caption"],
            bool(plan["captions"]),
        )
    except CaptionFailure as error:
        raise EditingFailure(error.code) from None
    plan["captions"] = rendered
    plan["editorial"]["caption_line_layout"] = report


def baseline_documents(
    root: Path,
    prepared: dict,
    transcript: Transcript,
    options: dict,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    package = settings.video_editing_library_dir
    video = next(s for s in prepared["probe"]["streams"] if s["codec_type"] == "video")
    width, height = video["width"], video["height"]
    if abs(width / height - 9 / 16) > 0.02:
        raise EditingFailure("EDITING_ORIENTATION_REVIEW_REQUIRED")
    # Keep the input aspect; no portrait crop of a landscape speaker.
    scale = min(1, _MASTER_MAX_WIDTH / width, _MASTER_MAX_HEIGHT / height)
    width, height = 2 * round(width * scale / 2), 2 * round(height * scale / 2)
    stroke_scale = max(1, height / 1280)
    duration = prepared["duration_ms"] / 1000
    fid = options["caption_font_id"]
    captions = caption_rows(transcript)
    config = read_json(package / "catalog/inputs/Z-M00.json")
    config["content"][
        "captions"
    ] = []  # Main transcript uses the original libass layer once.
    config["media"]["presenter"].update(
        path=str(root / "input/source.mp4"),
        offset_seconds=0,
        duration_seconds=duration,
        end_policy="error",
    )
    config["timing"].update(duration_seconds=duration, events={}, basis="explicit")
    config["output"]["path"] = str(root / "renders/source.mp4")
    plan: dict[str, Any] = {
        "schema": "commercial-talk-episode/1",
        "instance_dir": str(root),
        "source": {
            "path": str(root / "input/source.mp4"),
            "start_seconds": 0,
            "duration_seconds": duration,
            "role": "raw_presenter",
        },
        "output": {
            "path": "outputs/episode.mp4",
            "width": width,
            "height": height,
            "fps": 30,
        },
        "shots": [
            {
                "group_id": "Z-M00",
                "start_seconds": 0,
                "end_seconds": duration,
                "config": config,
                "intent": {
                    "expected_understanding": "保留完整实际口播",
                    "reason": "阶段一字幕链路，以原库普通口播组保留说话节奏。",
                },
            }
        ],
        "visual_scenes": [],
        "captions": [
            {k: v for k, v in c.items() if k != "token_ids"} for c in captions
        ],
        "typography": {
            "caption": {
                "font_id": fid,
                "size_px": round(height * 0.0375),
                "center_x_px": width / 2,
                "baseline_y_px": round(height * 0.80),
                "max_width_px": round(width * 0.84),
                "max_lines": 2,
                "fill": "#ffffff",
                "outline_color": "#111317",
                "outline_px": 2 * stroke_scale,
                "shadow_px": stroke_scale,
            }
        },
        "fx": [],
        "music": [],
        "mix": {"voice_gain_db": 0},
        "editorial": {
            "caption_segmentation": segmentation_metadata(),
            "source_verified": True,
            "audience_question": "这段实际录音说了什么？",
            "argument_outline": [u.text for u in transcript.utterances],
            "style_reason": "首条完整链路使用实际转录主字幕，不声称完成语义规划。",
        },
        "design": {
            "id": "tengli-baseline-subtitles-v1",
            "mode": "new",
            "sector": "本期口播",
            "audience": "本项目观众",
            "objective": "准确承载当前实际录音",
            "tone": "清晰",
            "background_strategy": "保留本期原景",
            "motion_direction": "保留普通口播，不另造替代动效",
            "sound_direction": "保留完整原声，本模式不加音乐和音效",
            "reason": "用户选择基础字幕模式",
            "caption_font_id": fid,
        },
        "layout_policy": {
            "reason": "按本期画幅放置字幕；人物遮挡和原硬字幕仍需视觉验收。",
            "subtitle_safe_rect": [0.08, 0.65, 0.84, 0.23],
        },
        "production": {
            "material_policy": "original_only",
            "no_production_annotations": True,
            "materials": [],
            "beats": [],
            "chapters": [],
        },
        "review": {"status": "unreviewed"},
    }
    if options["source_subtitles"] == "present":
        plan["captions"] = []
    layout_captions(plan, captions, settings)
    selection: dict[str, Any] = {
        "catalog_sha256": sha256(package / "catalog/groups.json"),
        "reference_mode": "none",
        "decisions": [
            {
                "shot_index": 0,
                "selected_group_id": "Z-M00",
                "viewer_task": "连续听清实际录音",
                "reason": "阶段一明确采用普通口播与原生主字幕路径；未运行模型选组。",
                "considered": [{"group_id": "Z-M00"}],
            }
        ],
    }
    # The original unified engine limits a native page to 15 seconds. Split
    # visual source ranges on that limit, never stretch or concatenate speech.
    boundaries = [index * 15.0 for index in range(math.ceil(duration / 15))]
    if len(boundaries) > 1 and duration - boundaries[-1] < 0.5:
        # Keep the native minimum by borrowing half a second from the prior page.
        boundaries[-1] -= 0.5
    boundaries.append(duration)
    shots = []
    for start, end in pairwise(boundaries):
        shot = copy.deepcopy(plan["shots"][0])
        shot.update(start_seconds=start, end_seconds=end)
        shot["config"]["media"]["presenter"].update(
            offset_seconds=start, duration_seconds=end - start
        )
        shot["config"]["timing"]["duration_seconds"] = end - start
        shots.append(shot)
    plan["shots"] = shots
    selection["decisions"] = [
        {**selection["decisions"][0], "shot_index": index}
        for index in range(len(shots))
    ]
    return plan, selection, captions


def compile_baseline(
    root: Path,
    prepared: dict,
    transcript: Transcript,
    options: dict,
    settings: Settings,
) -> dict[str, Any]:
    plan, selection, captions = baseline_documents(
        root, prepared, transcript, options, settings
    )
    atomic_json(root / "caption-anchors.json", captions)
    atomic_json(
        root / "caption-adapter-layout.json", plan["editorial"]["caption_line_layout"]
    )
    write_caption_receipt(
        root, transcript, captions, options["source_subtitles"] == "none"
    )
    atomic_json(root / "selection.json", selection)
    atomic_json(root / "bindings.json", {"resources": {}, "tools": {}})
    atomic_json(root / "episode.json", plan)
    return plan


def stop_hypit_runtimes(root: Path, settings: Settings) -> None:
    module = settings.video_editing_hypit_local_module
    if module is None:
        return
    profiles = list(
        (root / "hypit").glob("HY-A3-picture-parallel-3-*/hypit.runtime.json")
    )
    strip_root = root / "hypit-strips/work"
    for group in HYPIT_SIDECAR_GROUPS:
        profiles.extend(strip_root.glob(f"*/hypit/{group}/hypit.runtime.json"))
    allowed = (root.resolve() / "hypit", root.resolve() / "hypit-strips/work")
    for profile in profiles:
        workspace = profile.parent.resolve()
        if (
            not any(workspace.is_relative_to(parent) for parent in allowed)
            or not (workspace / ".hypit").is_dir()
        ):
            continue
        log = workspace / "tengli-runtime-down.log"
        with log.open("ab") as output:
            for _ in range(2):
                try:
                    result = subprocess.run(
                        [
                            "node",
                            str(module.resolve()),
                            "runtime",
                            "down",
                            "--workspace",
                            str(workspace),
                            "--runtime",
                            profile.name,
                            "--json",
                        ],
                        cwd=workspace,
                        env=environment(settings),
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        timeout=25,
                        check=False,
                        creationflags=creation_flags(),
                    )
                    output.write(f"\nexit={result.returncode}\n".encode())
                    break
                except subprocess.TimeoutExpired:
                    # Retry the same private runtime once after a transient timeout.
                    output.write(b"\ncleanup_error=TimeoutExpired\n")
                except OSError as error:
                    output.write(f"\ncleanup_error={type(error).__name__}\n".encode())
                    break


def _effect_layout_failed(root: Path) -> bool:
    try:
        replacements = read_json(root / "compile-diagnostics.json").get(
            "applied_effect_edits", []
        )
        if not replacements:
            return False
        shots = {row["shot_index"] for row in replacements}
        layout = read_json(root / "layout/review.json")
        return layout["status"] == "failed" and any(
            row["shot"] in shots for row in layout["errors"]
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def native_export(root: Path, settings: Settings, guard: Callable[[], None]) -> Path:
    python = settings.video_editing_python or sys.executable
    try:
        for command in ("check", "export"):
            run(
                [
                    python,
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    "app.video_editing_native",
                    "--package",
                    str(settings.video_editing_library_dir),
                    "--command",
                    command,
                    "--instance",
                    str(root),
                ],
                root,
                settings,
                guard,
                "native_" + command,
            )
    except EditingFailure as error:
        if error.code == "EDITING_NATIVE_EXPORT_FAILED" and _effect_layout_failed(root):
            raise EditingFailure("EDITING_EFFECT_LAYOUT_FAILED") from error
        raise
    finally:
        stop_hypit_runtimes(root, settings)
    return root / "outputs/episode.mp4"


def decode_av(
    path: Path, root: Path, settings: Settings, guard: Callable[[], None], name: str
) -> None:
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        root,
        settings,
        guard,
        name,
    )


def validate_result(
    path: Path,
    prepared: dict,
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
) -> dict[str, Any]:
    info = probe(path, settings)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None or not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise EditingFailure("EDITING_OUTPUT_TRACKS_INVALID")
    dimensions = {key: video[key] for key in ("width", "height")}
    expected = read_json(root / "episode.json")["output"]
    if dimensions != {key: expected[key] for key in dimensions}:
        raise EditingFailure("EDITING_OUTPUT_DIMENSIONS_INVALID")
    actual = round(float(info["format"]["duration"]) * 1000)
    if abs(actual - prepared["duration_ms"]) > 150:
        raise EditingFailure("EDITING_OUTPUT_DURATION_INVALID")
    decode_av(path, root, settings, guard, "decode_output")
    native = read_json(path.with_suffix(".delivery.json"))
    validation = {
        "decoded": True,
        "duration_ms": actual,
        "master_dimensions": dimensions,
        "source_duration_ms": prepared["duration_ms"],
        "sha256": sha256(path),
        "native_export_receipt": sha256(path.with_suffix(".delivery.json")),
        "native_source_sha256": native["source_clock"]["source_sha256"],
        "semantic_review": "unreviewed",
        "visual_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    if silent_tail := prepared.get("clock", {}).get("silent_tail"):
        validation["source_silent_tail"] = silent_tail
    if validation["native_source_sha256"] != prepared["source_sha256"]:
        raise EditingFailure("EDITING_OUTPUT_SOURCE_MISMATCH")
    if (root / "audio-plan.json").is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError("Native mix output changed")
            audio = verify_rendered_sound(
                root,
                native,
                read_json(root / "audio-plan.json"),
                settings.video_editing_library_dir,
            )
            atomic_json(root / "audio-validation.json", audio)
            validation["native_mix_validation"] = "passed"
        except (ValueError, KeyError, TypeError, OSError):
            raise EditingFailure("EDITING_SOUND_OUTPUT_INVALID") from None
    if (root / "caption-adapter-layout.json").is_file():
        try:
            validation["caption_layout"] = verify_native_caption_layout(root)
        except CaptionFailure as error:
            raise EditingFailure(error.code) from None
    if (root / "inset-layout-intent.json").is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError("Native inset output changed before validation")
            validation["native_inset_layout"] = verify_inset_layout(
                root, native["layout_review"]
            )
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise EditingFailure("EDITING_NATIVE_INSET_LAYOUT_INVALID") from None
    if (root / YY_OPENING_CAPTION_INTENT).is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError(
                    "Native scene output changed before caption validation"
                )
            validation["native_yy_opening_captions"] = verify_yy_opening_captions(
                root, native["layout_review"]
            )
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise EditingFailure(
                "EDITING_NATIVE_OPENING_CAPTION_LAYOUT_INVALID"
            ) from None
    if (root / AZL_LAYOUT_INTENT).is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError("Original panel output changed before validation")
            validation["native_azl_panel_layout"] = verify_azl_layout(root, native)
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise EditingFailure("EDITING_NATIVE_AZL_PANEL_LAYOUT_INVALID") from None
    if (root / CXBR_CAPTION_INTENT).is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError("Original B-roll output changed before validation")
            validation["native_cxbr_captions"] = verify_cxbr_captions(
                root, native["layout_review"]
            )
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise EditingFailure(
                "EDITING_NATIVE_CHENXI_CAPTION_LAYOUT_INVALID"
            ) from None
    if (root / UNIFIED_CAPTION_INTENT).is_file():
        try:
            if native["sha256"] != validation["sha256"]:
                raise ValueError("Original unified output changed before validation")
            validation["native_unified_captions"] = verify_unified_captions(
                root, native["layout_review"]
            )
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise EditingFailure(
                "EDITING_NATIVE_UNIFIED_CAPTION_LAYOUT_INVALID"
            ) from None
    atomic_json(root / "validation.json", validation)
    return validation
