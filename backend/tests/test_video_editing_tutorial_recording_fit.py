"""chenxi-broll e2e (2026-11-25, 10.1 s): a portrait clip in the landscape
recording window sat between flat white bars. The window is now filled with
a blurred cover of the same clip; the whole clip stays sharp in the middle."""

import subprocess
from types import SimpleNamespace

import imageio_ffmpeg
from PIL import Image

from app.video_editing_tutorial_render import LARGE_VIEW, _recording_graph

STEP = {
    "playback_segments": [
        {"source_in_ms": 0, "source_out_ms": 1000, "output_ms": 1000}
    ],
    "tail_hold_ms": 0,
    "large_crop": None,
}
LAYOUT = SimpleNamespace(viewport=(0, 0, 468, 560), pad_color="white")


def render_last_frame(tmp_path, normal_frames):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    source = tmp_path / "portrait.mp4"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=704x1248:rate=30:duration=1", str(source)],
        check=True,
    )  # fmt: skip
    graph = _recording_graph(STEP, LAYOUT, 30, normal_frames)
    frame = tmp_path / f"frame-{normal_frames}.png"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(source),
         "-filter_complex", graph + ";[full]select=eq(n\\,29)[out]",
         "-map", "[out]", "-frames:v", "1", str(frame)],
        check=True,
    )  # fmt: skip
    return Image.open(frame).convert("RGB")


def test_portrait_clip_in_large_window_has_no_white_bars(tmp_path):
    image = render_last_frame(tmp_path, 0)
    assert image.size == tuple(LARGE_VIEW[2:])
    for x in (4, image.width - 5):
        pixel = image.getpixel((x, image.height // 2))
        assert min(pixel) < 240, pixel  # Blurred clip, not a white bar.


def test_switch_from_normal_to_large_window_still_compiles(tmp_path):
    image = render_last_frame(tmp_path, 15)
    assert image.size == tuple(LARGE_VIEW[2:])
    graph = _recording_graph(STEP, LAYOUT, 30, 15)
    assert graph.count("boxblur") == 2 and "[fitnormalb]" in graph
