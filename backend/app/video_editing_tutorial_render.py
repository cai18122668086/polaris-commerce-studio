"""Template-independent, complete recording playback above a validated base.

The base render stays immutable. Tutorial content owns the demonstration clock,
one large recording view and narration pauses; the template supplies styling.
No model, transcription or image-generation provider is used here.
"""

from __future__ import annotations

import os
import wave
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from PIL import ImageFont

from .motion_library import atomic_json, read_json, sha256
from .video_editing_captioning import measured_caption_rows, text_boundaries
from .video_editing_contracts import Transcript
from .video_editing_pipeline import decode_av, probe, run
from .video_editing_template_audio import TEMPLATE_TRACKS
from .video_editing_tutorial_plan import (
    RecordingActivity,
    digest,
    frame_at,
    schedule,
    source_to_output,
    timestamp_expression,
)
from .video_editing_tutorial_sound import recording_sound
from .video_editing_tutorial_surfaces import (
    SIZE,
    Surface,
    chrome,
    fonts_for,
    large_chrome,
    presenter_mask,
    surface,
)

VERSION = "tengli.tutorial-presentation/5"
LARGE_VIEW = (0, 162, 1080, 1280)
CAPTION_SIZE = 62
CAPTION_WIDTH = SIZE[0] - 2 * (68 + 5)
RECORDING_TIMESCALE = 15360


def recording_activity(
    path: Path, duration: int, root: Path, settings: Any, guard: Callable
) -> RecordingActivity:
    """Sample local recording activity without sending any media to a model."""
    sample = root / (uuid4().hex + ".gray")
    w, h = 192, 108
    try:
        run(
            [
                settings.video_editing_ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-threads",
                "1",
                "-i",
                str(path),
                "-an",
                "-sn",
                "-vf",
                f"fps=8,scale={w}:{h},format=gray",
                "-t",
                str(duration / 1000),
                "-threads",
                "1",
                "-f",
                "rawvideo",
                "-y",
                str(sample),
            ],
            root,
            settings,
            guard,
            "tutorial_activity",
        )
        active: list[bool] = []
        broad: list[int] = []
        weight = np.zeros((h, w), dtype=np.int32)
        with sample.open("rb") as stream:
            previous = np.frombuffer(stream.read(w * h), dtype=np.uint8)
            while batch := stream.read(w * h * 48):
                guard()
                frames = np.frombuffer(batch, dtype=np.uint8).reshape(-1, w * h)
                rows = np.vstack((previous, frames)).astype(np.int16)
                changed = (np.abs(np.diff(rows, axis=0)) >= 16).reshape(-1, h, w)
                tiles = changed.reshape(len(changed), 9, 12, 12, 16).mean(axis=(2, 4))
                coverage = changed.mean(axis=(1, 2))
                active.extend(
                    ((tiles.max(axis=(1, 2)) >= 0.068) | (coverage >= 0.010)).tolist()
                )
                broad.extend(
                    len(active) - len(frames) + int(i)
                    for i in np.flatnonzero(coverage >= 0.08)
                )
                weight += changed.sum(axis=0, dtype=np.int32)
                previous = frames[-1]
    finally:
        sample.unlink(missing_ok=True)
    if len(active) < 4:
        return RecordingActivity()
    # A click can change only a tiny part of the screen. Check local tiles as
    # well as whole-screen motion, and keep a short lead-in around each change.
    steady: list[tuple[int, int]] = []
    for left in range(0, duration - 374, 500):
        right = min(duration, left + 500)
        a, b = max(0, left // 125 - 1), (right + 249) // 125
        if right <= (len(active) + 2) * 125 and not any(active[a:b]):
            if steady and steady[-1][1] == left:
                steady[-1] = (steady[-1][0], right)
            else:
                steady.append((left, right))
    # Zoom only if meaningful transitions are localized. Broad or ambiguous
    # movement uses the complete recording at full width.
    focus = None
    if weight.sum():
        bounds = []
        for projection in (weight.sum(axis=0), weight.sum(axis=1)):
            cumulative = projection.cumsum()
            low, high = np.searchsorted(
                cumulative, cumulative[-1] * np.array([0.025, 0.975])
            )
            margin = round(len(projection) * 0.08)
            bounds.append(
                (
                    max(0, int(low) - margin),
                    min(len(projection), int(high) + margin + 1),
                )
            )
        (x1, x2), (y1, y2) = bounds
        if (x2 - x1) * (y2 - y1) < 0.73 * w * h:
            x1, x2 = min(x1, w // 4), max(x2, 3 * w // 4)
            y1, y2 = min(y1, h // 4), max(y2, 3 * h // 4)
            focus = (x1 * 1000 // w, y1 * 1000 // h, x2 * 1000 // w, y2 * 1000 // h)
    detail = max(1400, (broad[0] + 1) * 125) if len(broad) >= 3 else None
    return RecordingActivity(tuple(steady), focus, detail)


def _recording_graph(
    step: dict, layout: Surface, frames: int, normal_frames: int
) -> str:
    # Integrate the per-segment speed along the input clock. No source interval
    # is removed and each boundary has the same presentation time on both sides.
    clock = []
    for row in step["playback_segments"]:
        start = row["source_in_ms"]
        length = row["source_out_ms"] - start
        clock.append(
            f"clip((PTS-STARTPTS)*TB-{start / 1000:.6f},0,{length / 1000:.6f})"
            f"*{row['output_ms'] / length:.12f}"
        )
    wc, hc = LARGE_VIEW[2:]
    nw, nh = layout.viewport[2:]
    pad = f":color={layout.pad_color}"

    def fit(width: int, height: int) -> str:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2{pad},setsar=1"
        )

    def crop() -> str:
        rect = step["large_crop"]
        if rect is None:
            return ""
        x, y, right, bottom = rect
        return (
            f"crop=w='max(2,trunc(iw*{right - x}/2000)*2)':"
            f"h='max(2,trunc(ih*{bottom - y}/2000)*2)':"
            f"x='trunc(iw*{x}/2000)*2':y='trunc(ih*{y}/2000)*2',"
        )

    prefix = (
        f"[0:v]settb=AVTB,setpts='({'+'.join(clock)})/TB',"
        f"fps=30:start_time=0,tpad=stop_mode=clone:"
        f"stop_duration={1 + step['tail_hold_ms'] / 1000},trim=end_frame={frames}"
    )
    normal = f"{fit(nw, nh)},pad={wc}:{hc}:0:0{pad}"
    large = crop() + fit(wc, hc)
    if normal_frames == 0:
        graph = f"{prefix},{large}"
    elif normal_frames == frames:
        graph = f"{prefix},{normal}"
    else:
        graph = (
            f"{prefix},split[a][b];"
            f"[a]trim=end_frame={normal_frames},setpts=PTS-STARTPTS,{normal}[small];"
            f"[b]trim=start_frame={normal_frames},setpts=PTS-STARTPTS,{large}[large];"
            "[small][large]concat=n=2:v=1:a=0"
        )
    # concat can emit a microsecond time base. The subsequent demuxer playlist
    # requires all recordings to use the same clock.
    return f"{graph},settb=expr=1/30,setpts=N[full]"


def prepare_recording(
    asset: dict,
    step: dict,
    cache: Path,
    settings: Any,
    guard: Callable,
    layout: Surface,
) -> dict:
    path = Path(asset["path"])
    if sha256(path) != step["asset_sha256"]:
        raise ValueError("Tutorial recording changed")
    start = frame_at(step["start_ms"])
    frames = frame_at(step["end_ms"]) - start
    normal_frames = (
        frames
        if step["large_start_ms"] is None
        else frame_at(step["large_start_ms"]) - start
    )
    viewport_size = layout.viewport[2:]
    key = digest(
        {
            "source": step["asset_sha256"],
            "playback": step["playback_segments"],
            "frames": frames,
            "normal_frames": normal_frames,
            "large_crop": step["large_crop"],
            "recording_timescale": RECORDING_TIMESCALE,
            "version": VERSION,
            "viewport_size": viewport_size,
            "background": layout.pad_color,
        }
    )
    parent = cache / key[:20]
    receipt = parent / "prepared.json"
    if receipt.exists():
        value = read_json(receipt)
        if all(sha256(Path(value[k])) == value[k + "_sha256"] for k in ["context"]):
            return value
        raise ValueError("Prepared tutorial recording changed")
    # Concurrent templates prepare privately and atomically select one complete file.
    root = parent / uuid4().hex[:8]
    root.mkdir(parents=True, exist_ok=False)
    context = root / "context.mp4"
    graph = _recording_graph(step, layout, frames, normal_frames)
    run(
        [
            settings.video_editing_ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-i",
            str(path),
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            graph,
            "-map",
            "[full]",
            "-frames:v",
            str(frames),
            "-r",
            "30",
            "-video_track_timescale",
            str(RECORDING_TIMESCALE),
            "-an",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "veryfast",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(context),
        ],
        root,
        settings,
        guard,
        "tutorial_material",
    )
    info = probe(context, settings)
    video = info["streams"][0]
    if (
        int(video.get("nb_frames", 0)) != frames
        or video["time_base"] != f"1/{RECORDING_TIMESCALE}"
        or video["duration_ts"] != frames * (RECORDING_TIMESCALE // 30)
    ):
        raise ValueError("Prepared tutorial recording has an invalid playback clock")
    value = {
        "context": str(context),
        "context_sha256": sha256(context),
        "source_sha256": step["asset_sha256"],
        "source_in_ms": 0,
        "source_out_ms": step["source_out_ms"],
        "rate": step["playback_rate"],
        "simultaneous_recording_views": 1,
    }
    candidate = root / "prepared.json"
    atomic_json(candidate, value)
    with suppress(FileExistsError):
        os.link(candidate, receipt)
    selected = read_json(receipt)
    if sha256(Path(selected["context"])) != selected["context_sha256"]:
        raise ValueError("Selected tutorial media changed")
    return selected


def _voice_chunks(reader: wave.Wave_read, clock: dict) -> Iterator[bytes]:
    start = 0
    for hold in [
        *clock["holds"],
        {"source_ms": clock["source_duration_ms"], "duration_ms": 0},
    ]:
        remaining = hold["source_ms"] * 48 - start
        while remaining:
            frames = min(remaining, 16384)
            chunk = reader.readframes(frames)
            if len(chunk) != frames * 4:
                raise ValueError("Tutorial narration ended before its timed boundary")
            yield chunk
            remaining -= frames
        remaining = hold["duration_ms"] * 48
        while remaining:
            frames = min(remaining, 16384)
            yield bytes(frames * 4)
            remaining -= frames
        start = hold["source_ms"] * 48


def decode_voice(
    source: Path,
    duration_ms: int,
    root: Path,
    settings: Any,
    guard: Callable,
    *,
    filename: str = "source-voice.wav",
) -> Path:
    baseline = root / filename
    run(
        [
            settings.video_editing_ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-af",
            "aresample=48000,aformat=channel_layouts=stereo,apad,"
            f"atrim=duration={duration_ms / 1000}",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(baseline),
        ],
        root,
        settings,
        guard,
        "tutorial_voice_reference",
    )
    return baseline


def quiet_boundaries(
    voice: Path, transcript: Transcript, steps: list[dict]
) -> dict[int, int]:
    wanted = {step["first_token_id"] for step in steps}
    wanted.update(
        following.id
        for prior, following in zip(
            transcript.tokens, transcript.tokens[1:], strict=False
        )
        if prior.text.endswith(("，", "、", "。", ",", ";", "；"))
    )
    last = next(t for t in transcript.tokens if t.id == steps[-1]["last_token_id"])
    points = sorted(
        {t.start_ms for t in transcript.tokens if t.id in wanted} | {last.end_ms}
    )
    result = {}
    with wave.open(str(voice)) as audio:
        for index, target in enumerate(points):
            lo = max(
                20, target - 205, (points[index - 1] + target) // 2 + 1 if index else 0
            )
            hi = min(
                transcript.duration_ms - 20,
                target + 205,
                (points[index + 1] + target) // 2 - 1
                if index + 1 < len(points)
                else transcript.duration_ms,
            )
            if lo > hi:
                continue
            audio.setpos((lo - 20) * 48)
            sound = np.frombuffer(audio.readframes((hi - lo + 40) * 48), dtype=np.int16)
            energy = (sound.reshape(-1, 96).astype(np.float64) ** 2).mean(axis=1)
            running = np.concatenate(([0.0], np.cumsum(energy)))
            power = (running[40:] - running[:-40]) / 40
            acceptable = np.flatnonzero(power <= max(float(power.min()) * 2, 10000))
            if len(acceptable) and float(power.min()) < 250000:
                chosen = min(
                    acceptable, key=lambda offset: abs(lo + int(offset) - target)
                )
                result[target] = lo + int(chosen)
    return result


def prepare_voice(
    baseline: Path,
    clock: dict,
    root: Path,
    guard: Callable,
    *,
    filename: str = "narration.wav",
) -> Path:
    proof = root / filename
    with wave.open(str(baseline)) as original, wave.open(str(proof), "wb") as output:
        output.setparams(original.getparams())
        for chunk in _voice_chunks(original, clock):
            guard()
            output.writeframesraw(chunk)
    return proof


def verify_voice(root: Path, clock: dict, guard: Callable) -> dict:
    with (
        wave.open(str(root / "source-voice.wav")) as original,
        wave.open(str(root / "narration.wav")) as actual,
    ):
        samples = actual.getnframes()
        source_samples = original.getnframes()
        if (
            (actual.getnchannels(), actual.getframerate(), actual.getsampwidth())
            != (2, 48000, 2)
            or samples != clock["duration_ms"] * 48
            or source_samples != clock["source_duration_ms"] * 48
        ):
            raise ValueError("Unexpected tutorial voice proof format or duration")
        for chunk in _voice_chunks(original, clock):
            guard()
            if chunk != actual.readframes(len(chunk) // 4):
                raise ValueError("Tutorial narration samples changed")
    return {
        "policy": "source-samples-with-explicit-silence/2",
        "status": "passed",
        "source_samples": source_samples,
        "output_samples": samples,
        "maximum_pcm_difference": 0,
        "sample_rate": 48000,
        "voice_rate": 1,
        "source_words_removed": False,
    }


def verify_views(
    final: Path, prepared: list[dict], clock: dict, layout: Surface
) -> dict:
    """Check actual first/middle/last demonstration frames, not only file decode."""
    capture = cv2.VideoCapture(str(final))
    samples = []
    try:
        for step, material in zip(clock["steps"], prepared, strict=True):
            reference = cv2.VideoCapture(material["context"])
            try:
                first = frame_at(step["start_ms"])
                length = max(1, frame_at(step["playback_end_ms"]) - first)
                large = step["large_start_ms"]
                switch = frame_at(large) - first if large is not None else length
                for frame in sorted(
                    {0, length // 2, length - 1, min(length - 1, switch)}
                ):
                    large_view = frame >= switch
                    x, y, width, height = LARGE_VIEW if large_view else layout.viewport
                    capture.set(cv2.CAP_PROP_POS_FRAMES, first + frame)
                    reference.set(cv2.CAP_PROP_POS_FRAMES, frame)
                    okay, actual = capture.read()
                    expected_okay, expected = reference.read()
                    if not okay or not expected_okay:
                        raise ValueError(
                            "Tutorial demonstration frame missing from delivery"
                        )
                    actual = actual[y : y + height, x : x + width]
                    if actual.shape != expected[:height, :width].shape:
                        raise ValueError(
                            "Tutorial full-context viewport changed or was cropped"
                        )
                    a = (
                        cv2.resize(
                            cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY), (246, 132)
                        ).astype(np.float32)
                        / 255
                    )
                    # The source and final clocks land on different 30fps grids.
                    # Match within one adjacent frame rather than treating a
                    # fast scroll across that frame boundary as hidden footage.
                    candidates = []
                    for offset in (-1, 0, 1):
                        reference.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame + offset))
                        valid, candidate = reference.read()
                        if valid:
                            gray = (
                                cv2.resize(
                                    cv2.cvtColor(
                                        candidate[:height, :width], cv2.COLOR_BGR2GRAY
                                    ),
                                    (246, 132),
                                ).astype(np.float32)
                                / 255
                            )
                            candidates.append(
                                (float(np.sqrt(np.mean((a - gray) ** 2))), gray)
                            )
                    error, b = min(candidates, key=lambda item: item[0])
                    edge_a = cv2.Sobel(a, cv2.CV_32F, 1, 0) + cv2.Sobel(
                        a, cv2.CV_32F, 0, 1
                    )
                    edge_b = cv2.Sobel(b, cv2.CV_32F, 1, 0) + cv2.Sobel(
                        b, cv2.CV_32F, 0, 1
                    )
                    denominator = float(np.linalg.norm(edge_a) * np.linalg.norm(edge_b))
                    correlation = (
                        float(np.sum(edge_a * edge_b)) / denominator
                        if denominator
                        else 1.0
                    )
                    if error > 0.045 or correlation < 0.65:
                        raise ValueError(
                            f"Tutorial material visibility failed: {step['asset_id']}"
                        )
                    samples.append(
                        {
                            "asset_id": step["asset_id"],
                            "playback_elapsed_ms": round(frame * 1000 / 30),
                            "view": "large" if large_view else "template",
                            "luma_rmse": round(error, 5),
                            "edge_correlation": round(correlation, 5),
                        }
                    )
            finally:
                reference.release()
    finally:
        capture.release()
    return {
        "status": "passed",
        "viewport_width_fraction": layout.viewport[2] / SIZE[0],
        "samples": samples,
    }


def _ass_time(milliseconds: int) -> str:
    cs = round(milliseconds / 10)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _caption_text(text: str, face: ImageFont.FreeTypeFont) -> str:
    text = (
        " ".join(text.splitlines())
        .strip()
        .replace("\\", "＼")
        .replace("{", "｛")
        .replace("}", "｝")
    )
    width = face.getlength(text)
    if width <= CAPTION_WIDTH:
        return text
    safe, preferred = text_boundaries(text)
    candidates = []
    for cut in sorted(safe - {0, len(text)}):
        left, right = text[:cut].rstrip(), text[cut:].lstrip()
        if not left or not right:
            continue
        widest = max(face.getlength(left), face.getlength(right))
        if widest <= CAPTION_WIDTH:
            candidates.append((cut not in preferred, widest, left, right))
    if candidates:
        _, _, left, right = min(candidates)
        return left + r"\N" + right
    # Preserve indivisible names and number/unit strings when a line cannot wrap.
    size = max(1, int(CAPTION_SIZE * CAPTION_WIDTH / width))
    return rf"{{\fs{size}}}" + text


def caption_file(
    root: Path, transcript: Transcript, clock: dict, layout: Surface, font: str
) -> Path:
    face = ImageFont.truetype(font, CAPTION_SIZE)
    font_name = face.getname()[0]

    def color(hex_rgb: str) -> str:
        return "&H00" + hex_rgb[4:6] + hex_rgb[2:4] + hex_rgb[:2]

    primary, outline = color(layout.caption_color), color(layout.caption_outline)
    columns = (
        "Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"
    )
    definition = (
        f"Style: Tutorial,{font_name},{CAPTION_SIZE},{primary},{primary},{outline},"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,3.8,0,2,68,68,"
        f"{layout.caption_margin if layout.replaces_caption else 318},1"
    )
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: {columns}
{definition}
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    steps = clock["steps"]
    windows = (
        [(steps[0]["start_ms"], steps[-1]["end_ms"])]
        if layout.replaces_caption
        else [
            (step["large_start_ms"], step["end_ms"])
            for step in steps
            if step["large_start_ms"] is not None
        ]
    )
    by_id = {t.id: t for t in transcript.tokens}
    holds = {hold["word_boundary_ms"]: hold for hold in clock["holds"]}
    for hold in clock["holds"]:
        gap = hold["output_start_ms"]
        resume = gap + hold["duration_ms"]
        windows = [
            (a, b)
            for start, end in windows
            for a, b in ((start, min(end, gap)), (max(start, resume), end))
            if a < b
        ]
    for cue in measured_caption_rows(transcript, max_chars=20):
        groups: list[list] = [[]]
        for tid in cue["token_ids"]:
            token = by_id[tid]
            if groups[-1] and token.start_ms in holds:
                groups.append([])
            groups[-1].append(token)
        for group in groups:
            text = _caption_text("".join(t.text for t in group), face)
            for start, end in windows:
                first = group[0].start_ms
                hold = holds.get(first)
                onset = (
                    hold["output_start_ms"] + hold["duration_ms"]
                    if hold is not None
                    else source_to_output(clock, first)
                )
                a = max(start, onset)
                b = min(end, source_to_output(clock, group[-1].end_ms, end=True))
                if a < b:
                    events.append(
                        f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},"
                        f"Tutorial,,0,0,0,,{text}"
                    )
    path = root / "tutorial-captions.ass"
    path.write_text(header + "\n".join(events) + "\n", encoding="utf8")
    return path


def concat_file(
    manifest: Path, files: list[Path], spans: list[float], *, images: bool = False
) -> Path:
    def line(path: Path) -> str:
        return "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'"

    rows = ["ffconcat version 1.0"]
    for path, span in zip(files, spans, strict=True):
        rows.append(line(path))
        if images:
            rows.append("option framerate 30")
            rows.append(f"duration {span:.9f}")
    if images:
        rows.extend([line(files[-1]), "option framerate 30"])
    manifest.write_text("\n".join(rows) + "\n", encoding="utf8")
    return manifest


def filter_path(path: Path) -> str:
    return path.as_posix().replace(":", r"\:").replace("'", r"\'")


def _activity_profiles(
    shared: dict, assets: dict, cache: Path, root: Path, settings: Any, guard: Callable
) -> dict[str, RecordingActivity]:
    profiles = {}
    for card in shared["context"]["recordings"]:
        asset_id, duration = card["id"], card["duration_ms"]
        path = Path(assets[asset_id]["path"])
        if sha256(path) != card["sha256"]:
            raise ValueError("Tutorial recording changed")
        key = digest([VERSION, card["sha256"], duration])
        profile_path = cache / f"activity-{key[:20]}.json"
        if profile_path.exists():
            value = read_json(profile_path)
            profile = RecordingActivity(
                tuple(tuple(interval) for interval in value["steady"]),
                tuple(value["focus"]) if value["focus"] is not None else None,
                value["detail_from_ms"],
            )
        else:
            profile = recording_activity(path, duration, root, settings, guard)
            candidate = cache / f"activity-{uuid4().hex}.json"
            atomic_json(
                candidate,
                {
                    "steady": profile.steady,
                    "focus": profile.focus,
                    "detail_from_ms": profile.detail_from_ms,
                },
            )
            try:
                with suppress(FileExistsError):
                    os.link(candidate, profile_path)
            finally:
                candidate.unlink(missing_ok=True)
        profiles[asset_id] = profile
    return profiles


def _interval(start: int, end: int) -> str:
    return f"gte(t+0.000001,{start}/30)*lt(t+0.000001,{end}/30)"


def render_tutorial(
    base: Path,
    source: Path,
    transcript: Transcript,
    assets: dict,
    shared: dict,
    template_id: str,
    root: Path,
    settings: Any,
    guard: Callable,
    *,
    preview_at: float | None = None,
) -> tuple[Path, dict]:
    if sha256(source) != transcript.source_sha256:
        raise ValueError("Tutorial narration source changed")
    root.mkdir(parents=True, exist_ok=True)
    layout = surface(template_id)
    _, caption_font = fonts_for(template_id)
    cache = (
        settings.video_editing_tasks_dir
        / "_tutorial"
        / shared["context"]["key"]
        / "media"
    )
    profiles = _activity_profiles(shared, assets, cache, root, settings, guard)
    baseline_voice = decode_voice(source, transcript.duration_ms, root, settings, guard)
    quiet = quiet_boundaries(baseline_voice, transcript, shared["intent"]["steps"])
    clock = schedule(shared, transcript, profiles, quiet)
    steps = clock["steps"]
    prepared = [
        prepare_recording(
            assets[step["asset_id"]], step, cache, settings, guard, layout
        )
        for step in steps
    ]
    atomic_json(root / "tutorial-clock.json", clock)
    large_intervals = [
        (frame_at(step["large_start_ms"]), frame_at(step["end_ms"]))
        for step in steps
        if step["large_start_ms"] is not None
    ]
    large_active = "+".join(_interval(a, b) for a, b in large_intervals) or "0"
    captions = (
        caption_file(root, transcript, clock, layout, caption_font)
        if layout.replaces_caption or large_intervals
        else None
    )
    expression = timestamp_expression(clock)
    duration = clock["duration_ms"] / 1000
    safety_tail = sum(h["duration_ms"] for h in clock["holds"]) / 1000 + 1
    # The held parts of the base timeline are hidden by the full recording plate.
    # Audio is packetized at 1 ms and hard-padded, preserving every voice sample.
    args = [
        settings.video_editing_ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-filter_complex_threads",
        "1",
        "-threads",
        "1",
        "-i",
        str(base),
        "-threads",
        "1",
        "-i",
        str(source),
    ]
    graph = [
        f"[0:v]setpts='{expression}',fps=30,tpad=stop_mode=clone:stop_duration={safety_tail},scale=1080:1920,setsar=1,format=yuv420p[base]",
    ]
    labels = [step["label"] for step in clock["steps"]]
    panels, panel_spans, spans = [], [], []
    for step in steps:
        first, last = frame_at(step["start_ms"]), frame_at(step["end_ms"])
        cut = (
            last if step["large_start_ms"] is None else frame_at(step["large_start_ms"])
        )
        spans.append((last - first) / 30)
        if cut > first:
            tile = root / f"step-{step['index']:02d}.png"
            chrome(layout, template_id, step, labels).save(tile)
            panels.append(tile)
            panel_spans.append((cut - first) / 30)
        if last > cut:
            tile = root / f"step-{step['index']:02d}-large.png"
            large_chrome(layout, template_id, step).save(tile)
            panels.append(tile)
            panel_spans.append((last - cut) / 30)

    for manifest in (
        concat_file(root / "panels.ffconcat", panels, panel_spans, images=True),
        concat_file(
            root / "recordings.ffconcat", [Path(m["context"]) for m in prepared], spans
        ),
    ):
        args += ["-threads", "1", "-f", "concat", "-safe", "0", "-i", str(manifest)]
    if any(
        a["end_ms"] != b["start_ms"] for a, b in zip(steps, steps[1:], strict=False)
    ):
        raise ValueError("Tutorial demonstration timeline is not continuous")
    start, end = frame_at(steps[0]["start_ms"]), frame_at(steps[-1]["end_ms"])
    active = _interval(start, end)
    normal_active = f"({active})*not({large_active})"
    shift = f"PTS-STARTPTS+{start}/30/TB"
    x, y, vw, vh = layout.viewport
    if layout.native_box:
        _, _, nw, nh = layout.native_box
        graph += [
            "[base]split[base_full][native_input]",
            f"[native_input]scale={nw}:{nh},setsar=1[native]",
        ]
        base_label = "base_full"
    else:
        base_label = "base"
    graph += [
        f"[2:v]format=rgba,setpts='{shift}'[panels]",
        f"[{base_label}][panels]overlay=0:0:enable='{active}':eof_action=pass[styled]",
    ]
    if large_intervals:
        graph += [
            f"[3:v]settb=AVTB,setpts='{shift}',split[reference][large_recording]",
            f"[styled][large_recording]overlay={LARGE_VIEW[0]}:{LARGE_VIEW[1]}:"
            f"enable='{large_active}':eof_action=pass[large_screen]",
        ]
        current = "large_screen"
    else:
        graph.append(f"[3:v]settb=AVTB,setpts='{shift}'[reference]")
        current = "styled"
    graph += [
        f"[reference]crop={vw}:{vh}:0:0[recordings]",
        f"[{current}][recordings]overlay={x}:{y}:enable='{normal_active}':eof_action=pass[screen]",
    ]
    current = "screen"
    if layout.native_box:
        nx, ny = layout.native_box[:2]
        graph.append(
            f"[screen][native]overlay={nx}:{ny}:enable='{normal_active}':eof_action=pass[native_scene]"
        )
        current = "native_scene"
    if layout.presenter:
        px, py, pw, ph = layout.presenter
        mask = root / "presenter-mask.png"
        presenter_mask(layout, mask)
        args += ["-loop", "1", "-framerate", "30", "-i", str(mask)]
        graph += [
            f"[1:v]setpts='{expression}',fps=30,tpad=stop_mode=clone:stop_duration={safety_tail},scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1,format=yuv420p[pip]",
            "[4:v]format=gray[alpha]",
            "[pip][alpha]alphamerge[presenter]",
            f"[{current}][presenter]overlay={px}:{py}:enable='{normal_active}':eof_action=pass[person]",
        ]
        current = "person"
    if captions:
        graph.append(
            f"[{current}]subtitles=filename='{filter_path(captions)}':fontsdir='{filter_path(Path(caption_font).parent)}'[final]"
        )
        current = "final"
    if preview_at is not None:
        still = root / "preview.jpg"
        run(
            args
            + [
                "-filter_complex",
                ";".join(graph),
                "-map",
                f"[{current}]",
                "-ss",
                str(preview_at),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(still),
            ],
            root,
            settings,
            guard,
            "tutorial_preview",
        )
        viewport = (
            LARGE_VIEW
            if any(a / 30 <= preview_at < b / 30 for a, b in large_intervals)
            else layout.viewport
        )
        return still, {"viewport": viewport, "surface": layout.name}
    final = root / "tutorial-final.mp4"
    voice = prepare_voice(baseline_voice, clock, root, guard)
    voice_input = 5 if layout.presenter else 4
    voice_map = f"{voice_input}:a:0"
    sound = None
    if template_id in TEMPLATE_TRACKS:
        native = decode_voice(
            base,
            transcript.duration_ms,
            root,
            settings,
            guard,
            filename="native-mix-source.wav",
        )
        voice = prepare_voice(native, clock, root, guard, filename="native-mix.wav")
        fx, sound = recording_sound(clock, assets, root, settings, guard)
        args += ["-i", str(voice), "-i", str(fx)]
        graph += [
            f"[{voice_input + 1}:a:0]aformat=channel_layouts=stereo[recording_fx]",
            f"[{voice_input}:a:0][recording_fx]amix=inputs=2:duration=first:normalize=0,"
            "alimiter=limit=0.97:level=0:latency=1[mixed_voice]",
        ]
        voice_map = "[mixed_voice]"
    else:
        args += ["-i", str(voice)]
    args += [
        "-filter_complex",
        ";".join(graph),
        "-map",
        f"[{current}]",
        "-map",
        voice_map,
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-y",
        str(final),
    ]
    atomic_json(root / "render-command.json", {"args": args, "version": VERSION})
    run(args, root, settings, guard, "tutorial_compose")
    return final, validate_tutorial(
        final,
        base,
        source,
        transcript,
        shared,
        clock,
        prepared,
        template_id,
        root,
        settings,
        guard,
        sound=sound,
    )


def validate_tutorial(
    final: Path,
    base: Path,
    source: Path,
    transcript: Transcript,
    shared: dict,
    clock: dict,
    prepared: list[dict],
    template_id: str,
    root: Path,
    settings: Any,
    guard: Callable,
    *,
    sound: dict | None = None,
) -> dict:
    decode_av(final, root, settings, guard, "decode_tutorial")
    info = probe(final, settings)
    measured = round(float(info["format"]["duration"]) * 1000)
    if abs(measured - clock["duration_ms"]) > 100:
        raise ValueError("Tutorial output clock changed")
    voice = verify_voice(root, clock, guard)
    layout = surface(template_id)
    views = verify_views(final, prepared, clock, layout)
    receipt = {
        "version": VERSION,
        "decoded": True,
        "duration_ms": measured,
        "width": 1080,
        "height": 1920,
        "sha256": sha256(final),
        "source_sha256": transcript.source_sha256,
        "base_sha256": sha256(base),
        "content_sha256": shared["sha256"],
        "clock_sha256": clock["sha256"],
        "template_id": template_id,
        "coverage": {
            "selected": len(shared["context"]["recordings"]),
            "played": len(clock["steps"]),
            "missing_asset_ids": [],
            "all_source_ranges_complete": True,
        },
        "recordings": clock["steps"],
        "context_box": list(layout.viewport),
        "large_view_box": list(LARGE_VIEW),
        "template_surface": layout.name,
        "simultaneous_recording_views": 1,
        "narration_rate": 1,
        "narration_holds": clock["holds"],
        "model_calls": 0,
        "narration_validation": voice,
        "material_view_validation": views,
        **({"recording_sound": sound} if sound is not None else {}),
        "visual_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    atomic_json(root / "tutorial-validation.json", receipt)
    return receipt
