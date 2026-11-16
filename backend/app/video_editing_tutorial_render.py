"""Template-independent, complete recording playback above a validated base.

The base render stays immutable. Tutorial content owns the demonstration clock,
one large recording view and narration pauses; the template supplies styling.
No model, transcription or image-generation provider is used here.
"""

from __future__ import annotations

import os
import wave
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from PIL import ImageFont

from .motion_library import atomic_json, read_json, sha256
from .video_editing_captioning import measured_caption_rows
from .video_editing_contracts import Transcript
from .video_editing_pipeline import decode_av, probe, run
from .video_editing_tutorial_plan import (
    digest,
    schedule,
    source_to_output,
    timestamp_expression,
)
from .video_editing_tutorial_surfaces import (
    SIZE,
    Surface,
    chrome,
    fonts_for,
    presenter_mask,
    surface,
)

VERSION = "tengli.tutorial-presentation/2"


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
    key = digest(
        {
            "source": step["asset_sha256"],
            "hold_ms": step["tail_hold_ms"],
            "version": VERSION,
            "viewport_size": layout.viewport[2:],
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
    hold = step["tail_hold_ms"] / 1000
    context = root / "context.mp4"
    full_w, full_h = layout.viewport[2:]
    graph = (
        f"[0:v]scale={full_w}:{full_h}:force_original_aspect_ratio=decrease,"
        f"pad={full_w}:{full_h}:(ow-iw)/2:(oh-ih)/2:color={layout.pad_color},setsar=1,fps=30,"
        f"tpad=stop_mode=clone:stop_duration={hold}[full]"
    )
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
    for output in (context,):
        measured = round(float(probe(output, settings)["format"]["duration"]) * 1000)
        if measured < step["source_out_ms"] + step["tail_hold_ms"] - 40:
            raise ValueError(
                "Prepared tutorial recording ended before its full source range"
            )
    value = {
        "context": str(context),
        "context_sha256": sha256(context),
        "source_sha256": step["asset_sha256"],
        "source_in_ms": 0,
        "source_out_ms": step["source_out_ms"],
        "rate": 1,
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


def verify_voice(
    source: Path, proof: Path, clock: dict, root: Path, settings: Any, guard: Callable
) -> dict:
    baseline = root / "source-voice.wav"
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
            f"atrim=duration={clock['source_duration_ms'] / 1000}",
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

    def pcm(path: Path) -> np.ndarray:
        with wave.open(str(path)) as stream:
            if (
                stream.getnchannels() != 2
                or stream.getframerate() != 48000
                or stream.getsampwidth() != 2
            ):
                raise ValueError("Unexpected tutorial voice proof format")
            return np.frombuffer(
                stream.readframes(stream.getnframes()), dtype=np.int16
            ).reshape(-1, 2)

    original, actual = pcm(baseline), pcm(proof)
    parts = []
    start = 0
    for hold in clock["holds"]:
        stop = hold["source_ms"] * 48
        parts.extend(
            [
                original[start:stop],
                np.zeros((hold["duration_ms"] * 48, 2), dtype=np.int16),
            ]
        )
        start = stop
    parts.append(original[start:])
    expected = np.concatenate(parts)
    if len(actual) != len(expected):
        raise ValueError("Tutorial voice duration or padding changed")
    difference = np.abs(actual.astype(np.int32) - expected.astype(np.int32))
    if int(difference.max(initial=0)) > 1:
        raise ValueError(
            "Tutorial narration samples changed outside the inserted silence"
        )
    return {
        "policy": "source-samples-with-explicit-silence/1",
        "status": "passed",
        "source_samples": len(original),
        "output_samples": len(actual),
        "maximum_pcm_difference": int(difference.max(initial=0)),
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
    x, y, width, height = layout.viewport
    try:
        for step, material in zip(clock["steps"], prepared, strict=True):
            reference = cv2.VideoCapture(material["context"])
            try:
                duration = step["source_out_ms"] / 1000
                for elapsed in (
                    min(0.25, duration / 4),
                    duration / 2,
                    max(0, duration - 0.10),
                ):
                    capture.set(
                        cv2.CAP_PROP_POS_MSEC, step["start_ms"] + elapsed * 1000
                    )
                    reference.set(cv2.CAP_PROP_POS_MSEC, elapsed * 1000)
                    okay, actual = capture.read()
                    expected_okay, expected = reference.read()
                    if not okay or not expected_okay:
                        raise ValueError(
                            "Tutorial demonstration frame missing from delivery"
                        )
                    actual = actual[y : y + height, x : x + width]
                    if actual.shape != expected.shape:
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
                        reference.set(
                            cv2.CAP_PROP_POS_FRAMES, max(0, int(elapsed * 30) + offset)
                        )
                        valid, candidate = reference.read()
                        if valid:
                            gray = (
                                cv2.resize(
                                    cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY),
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
                            "source_elapsed_ms": round(elapsed * 1000),
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
        "viewport_width_fraction": width / SIZE[0],
        "samples": samples,
    }


def _ass_time(milliseconds: int) -> str:
    cs = round(milliseconds / 10)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def caption_file(
    root: Path, transcript: Transcript, clock: dict, layout: Surface, font: str
) -> Path:
    font_name = ImageFont.truetype(font, 52).getname()[0]

    def color(hex_rgb: str) -> str:
        return "&H00" + hex_rgb[4:6] + hex_rgb[2:4] + hex_rgb[:2]

    primary, outline = color(layout.caption_color), color(layout.caption_outline)
    columns = (
        "Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"
    )
    definition = (
        f"Style: Tutorial,{font_name},52,{primary},{primary},{outline},"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,68,68,{layout.caption_margin},1"
    )
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: {columns}
{definition}
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    start, end = clock["steps"][0]["start_ms"], clock["steps"][-1]["end_ms"]
    by_id = {t.id: t for t in transcript.tokens}
    holds = {hold["source_ms"] for hold in clock["holds"]}
    for cue in measured_caption_rows(transcript, max_chars=20):
        groups: list[list] = [[]]
        for tid in cue["token_ids"]:
            token = by_id[tid]
            if groups[-1] and token.start_ms in holds:
                groups.append([])
            groups[-1].append(token)
        for group in groups:
            a = max(start, source_to_output(clock, group[0].start_ms))
            b = min(end, source_to_output(clock, group[-1].end_ms, end=True))
            if a >= b:
                continue
            text = (
                "".join(t.text for t in group)
                .replace("\\", "＼")
                .replace("{", "｛")
                .replace("}", "｝")
                .replace("\n", r"\N")
            )
            events.append(
                f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Tutorial,,0,0,0,,{text}"
            )
    path = root / "tutorial-captions.ass"
    path.write_text(header + "\n".join(events) + "\n", encoding="utf8")
    return path


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
    clock = schedule(shared, transcript)
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
    prepared = [
        prepare_recording(
            assets[step["asset_id"]], step, cache, settings, guard, layout
        )
        for step in clock["steps"]
    ]
    atomic_json(root / "tutorial-clock.json", clock)
    captions = (
        caption_file(root, transcript, clock, layout, caption_font)
        if layout.replaces_caption
        else None
    )
    expression = timestamp_expression(clock)
    duration = clock["duration_ms"] / 1000
    safety_tail = sum(h["duration_ms"] for h in clock["holds"]) / 1000 + 1
    # One timestamp transform inserts holds across the entire base and speaker.
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
    if preview_at is None:
        graph.append(
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,asetnsamples=n=48:p=0,asetpts='{expression}',aresample=async=1:min_hard_comp=0.0005:first_pts=0,apad,atrim=duration={duration},asplit=2[voice][voice_proof]"
        )
    labels = [step["label"] for step in clock["steps"]]
    panels = []
    for step in clock["steps"]:
        tile = root / f"step-{step['index']:02d}.png"
        chrome(layout, template_id, step, labels).save(tile)
        panels.append(tile)
    spans = [(step["end_ms"] - step["start_ms"]) / 1000 for step in clock["steps"]]

    def concat(name: str, files: list[Path], *, images: bool = False) -> Path:
        manifest = root / name

        def line(path: Path) -> str:
            return "file '" + path.resolve().as_posix().replace("'", "'\\''") + "'"

        rows = ["ffconcat version 1.0"]
        for path, span in zip(files, spans, strict=True):
            rows.append(line(path))
            if images:
                rows.append("option framerate 30")
            rows.append(f"duration {span:.3f}")
        if images:
            rows.extend([line(files[-1]), "option framerate 30"])
        manifest.write_text("\n".join(rows) + "\n", encoding="utf8")
        return manifest

    for manifest in (
        concat("panels.ffconcat", panels, images=True),
        concat("recordings.ffconcat", [Path(m["context"]) for m in prepared]),
    ):
        args += ["-threads", "1", "-f", "concat", "-safe", "0", "-i", str(manifest)]
    steps = clock["steps"]
    if any(
        a["end_ms"] != b["start_ms"] for a, b in zip(steps, steps[1:], strict=False)
    ):
        raise ValueError("Tutorial demonstration timeline is not continuous")
    start = steps[0]["start_ms"] / 1000
    end = steps[-1]["end_ms"] / 1000
    active = f"gte(t,{start})*lt(t,{end})"
    shift = f"PTS-STARTPTS+{start}/TB"
    x, y = layout.viewport[:2]
    graph += [
        f"[2:v]format=rgba,setpts='{shift}'[panels]",
        f"[3:v]setpts='{shift}'[recordings]",
        f"[base][panels]overlay=0:0:enable='{active}':eof_action=pass[styled]",
        f"[styled][recordings]overlay={x}:{y}:enable='{active}':eof_action=pass[screen]",
    ]
    current = "screen"
    if layout.presenter:
        px, py, pw, ph = layout.presenter
        mask = root / "presenter-mask.png"
        presenter_mask(layout, mask)
        args += ["-loop", "1", "-framerate", "30", "-i", str(mask)]
        graph += [
            f"[1:v]setpts='{expression}',fps=30,tpad=stop_mode=clone:stop_duration={safety_tail},scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1,format=yuv420p[pip]",
            "[4:v]format=gray[alpha]",
            "[pip][alpha]alphamerge[presenter]",
            f"[screen][presenter]overlay={px}:{py}:enable='{active}':eof_action=pass[person]",
        ]
        current = "person"
    if captions:

        def escape(path: Path) -> str:
            return path.as_posix().replace(":", r"\:").replace("'", r"\'")

        graph.append(
            f"[{current}]subtitles=filename='{escape(captions)}':fontsdir='{escape(Path(caption_font).parent)}'[final]"
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
        return still, {"viewport": layout.viewport, "surface": layout.name}
    final = root / "tutorial-final.mp4"
    args += [
        "-filter_complex",
        ";".join(graph),
        "-map",
        f"[{current}]",
        "-map",
        "[voice]",
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
        "-map",
        "[voice_proof]",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",
        str(root / "narration.wav"),
    ]
    atomic_json(root / "render-command.json", {"args": args, "version": VERSION})
    run(args, root, settings, guard, "tutorial_compose")
    return final, validate_tutorial(
        final,
        base,
        source,
        transcript,
        shared,
        prepared,
        template_id,
        root,
        settings,
        guard,
    )


def validate_tutorial(
    final: Path,
    base: Path,
    source: Path,
    transcript: Transcript,
    shared: dict,
    prepared: list[dict],
    template_id: str,
    root: Path,
    settings: Any,
    guard: Callable,
) -> dict:
    clock = schedule(shared, transcript)
    decode_av(final, root, settings, guard, "decode_tutorial")
    info = probe(final, settings)
    measured = round(float(info["format"]["duration"]) * 1000)
    if abs(measured - clock["duration_ms"]) > 100:
        raise ValueError("Tutorial output clock changed")
    voice = verify_voice(source, root / "narration.wav", clock, root, settings, guard)
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
        "template_surface": layout.name,
        "simultaneous_recording_views": 1,
        "narration_rate": 1,
        "narration_holds": clock["holds"],
        "model_calls": 0,
        "narration_validation": voice,
        "material_view_validation": views,
        "visual_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    atomic_json(root / "tutorial-validation.json", receipt)
    return receipt
