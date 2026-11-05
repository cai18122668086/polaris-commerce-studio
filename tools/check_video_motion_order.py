"""Compare non-face frames to diagnose forward/reverse template extension.

Closest-frame matching is evidence of temporal order, not a perceptual quality
score. Nearly static poses and dissolves make individual matches ambiguous.
"""

import argparse
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageChops


def samples(path: Path, fps=4, chest_only=False):
    reader = imageio_ffmpeg.read_frames(str(path))
    metadata = next(reader)
    reader.close()
    w, h = metadata["source_size"]
    if chest_only:
        x, y, cw, ch = int(w / 3), int(h * 0.37), int(w / 3), int(h * 0.23)
    else:
        x, y, cw, ch = int(w * 0.08), int(h * 0.315), int(w * 0.84), int(h * 0.65)
    width, height = 96, 96
    raw = subprocess.check_output(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},crop={cw}:{ch}:{x}:{y},scale={width}:{height},format=gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
    )
    size = width * height
    return [
        Image.frombytes("L", (width, height), raw[i : i + size])
        for i in range(0, len(raw), size)
    ]


def distance(a, b):
    histogram = ImageChops.difference(a, b).histogram()
    return sum(i * count for i, count in enumerate(histogram)) / (a.width * a.height)


def compare(source: Path, result: Path, output: Path):
    fps = 4
    a, b = samples(source, fps), samples(result, fps)
    matches = []
    for index, frame in enumerate(b):
        error, source_index = min(
            (distance(frame, original), i) for i, original in enumerate(a)
        )
        matches.append(
            {
                "result_seconds": index / fps,
                "closest_source_seconds": source_index / fps,
                "pixel_error_0_255": round(error, 4),
            }
        )
    report = {
        "source": str(source),
        "result": str(result),
        "sample_fps": fps,
        "mean_best_match_error": sum(m["pixel_error_0_255"] for m in matches)
        / len(matches),
        "limitation": "Static poses and transitions can yield ambiguous nearest-frame matches; review moving sections and longer timestamp sequences.",
        "matches": matches,
    }
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "mean_best_match_error": report["mean_best_match_error"],
                "moving_samples_every_2s": matches[::8],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    compare(args.source, args.result, args.output)
