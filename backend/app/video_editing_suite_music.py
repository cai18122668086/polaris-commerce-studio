"""Default music for suites with an approved soundtrack."""

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .config import Settings
from .motion_library import sha256
from .video_editing_pipeline import run
from .video_editing_render_edits import MUSIC_REDUCTION_DB
from .video_editing_template_audio import MUSIC_SUBDIRECTORY


class SuiteMusic(NamedTuple):
    title: str
    filename: str
    sha256: str
    offset: float
    entrance: float
    gain_db: float


SUITE_MUSIC = {
    "bihuo-33-v1": SuiteMusic(
        "technology快感节拍",
        "news-pulse.m4a",
        "791529ae245fa2183ea9ffbfb08f6d094ca6a34bbdfc399e7fddd2c12e0451d7",
        0.93,
        3.20,
        -17.5,
    ),
    "bihuo-04-v1": SuiteMusic(
        "太空感 爬升节拍",
        "application-space.m4a",
        "5cdf8fd64a981e547e066d69382e54c84c765d31ba47e4005de165b85c1b607b",
        0.20,
        2.10,
        -8.8,
    ),
    "bihuo-10-v1": SuiteMusic(
        "green to blue",
        "lifestyle-green.m4a",
        "d44bee342ef1cb66ee68603e927d3fe7e1b1b5957163011482904fe18922fedb",
        0.08,
        2.40,
        -15.2,
    ),
}


def music_file(settings: Settings, track: SuiteMusic) -> Path:
    return settings.video_editing_tasks_dir / MUSIC_SUBDIRECTORY / track.filename


def mix_suite_music(
    master: Path,
    speech: Path,
    template_id: str,
    preference: str,
    duration_ms: int,
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
) -> tuple[Path, dict] | None:
    track = SUITE_MUSIC.get(template_id)
    if track is None or preference == "off":
        return None
    asset = music_file(settings, track)
    if asset.is_symlink() or not asset.is_file() or sha256(asset) != track.sha256:
        raise ValueError("Approved suite music asset is missing or changed")
    duration = duration_ms / 1000
    entrance = min(track.entrance, max(0, duration - 1.5))
    gain = track.gain_db - (MUSIC_REDUCTION_DB if preference == "lower" else 0)
    # Keep the original speech separate as the compressor's detector. Cue peaks
    # do not trigger ducking and tutorial holds let the bed continue underneath.
    fade_in = 0.25 if template_id == "bihuo-33-v1" else 0.42
    music_length = duration - entrance
    fade_out = min(1, music_length / 2)
    graph = (
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[master];"
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[voice];"
        f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain}dB,"
        f"atrim=duration={music_length:.6f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d={fade_in},"
        f"afade=t=out:st={music_length - fade_out:.6f}:d={fade_out},"
        f"adelay={round(entrance * 1000)}:all=1[bed];"
        "[bed][voice]sidechaincompress=threshold=0.016:ratio=5:attack=24:"
        "release=170:makeup=1:mix=0.55:detection=rms[ducked];"
        "[master][ducked]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.97:level=0:latency=1[audio]"
    )
    root.mkdir(parents=True, exist_ok=True)
    final = root / "final.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(master),
            "-i",
            str(speech),
            "-stream_loop",
            "-1",
            "-ss",
            str(track.offset),
            "-i",
            str(asset),
            "-filter_complex",
            graph,
            "-map",
            "0:v:0",
            "-map",
            "[audio]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(final),
        ],
        root,
        settings,
        guard,
        "suite_music",
    )
    return final, {
        "title": track.title,
        "asset_sha256": track.sha256,
        "source_start_ms": round(track.offset * 1000),
        "entry_ms": round(entrance * 1000),
        "gain_db": round(gain, 2),
        "speech_ducking": True,
    }
