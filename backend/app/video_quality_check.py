"""Automated quality checks for one full-suite render directory.

Usage::

    python -m app.video_quality_check RENDER_ROOT [--preview PATH]
        [--ffmpeg ffmpeg] [--report PATH]

``RENDER_ROOT`` holds ``suite-input.json`` and ``suite-render/`` (with
``final.mp4`` and ``layers-timeline.jsonl``). Metrics follow section 6 of
docs/video-editing-upgrade-plan-20261125.md:

- sync_gap: visual onset (frame where a new element completes half of its
  entry change: 50% opacity, or half of a reveal inside an opaque card)
  minus the start of the spoken phrase it belongs to, per sync target;
- material_dwell: seconds each matched material stays at >= 50% opacity;
- fps_cfr: constant packet duration and timestamps at the target rate;
- dup_in_motion: decoded frames identical to their predecessor while an
  overlay layer is animating;
- preview: the review proxy keeps the master's motion (near-duplicate frames
  versus the master scaled to the proxy size), with its bitrate reported.

Only ffmpeg is required (no ffprobe). Exit status is 0 when every gated check
passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

from .bihuo_suite.layer_timeline import load_grids

FPS = 25
EXCLUDED_ROLES = re.compile(r"presenter|caption|subtitle|background|stage|raw|source")
MIN_CELL_CHANGE = 24
MIN_EVENT_CELLS = 2
EVENT_GAP_FRAMES = 3
MATCH_WINDOW = (-1.0, 1.5)
# Chapter labels are optional per template (most suites draw none), so they
# are reported but never gate the sync check.
GATED_KINDS = frozenset({"material", "point", "feature"})
SYNC_MEDIAN_RANGE_S = (-0.25, 0.0)
THRESHOLDS: dict[str, Any] = {
    "sync_max_s": 0.12,
    "sync_fail_s": 0.30,
    "material_dwell_s": 1.2,
    # Review proxy must keep the master's motion: its near-duplicate count
    # (mpdecimate) may exceed the master scaled to the same size by <= 3%.
    "preview_extra_near_duplicates": 0.03,
}


def read_timeline(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def overlay_roles(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        name: row
        for name, row in frame.get("roles", {}).items()
        if not EXCLUDED_ROLES.search(name)
    }


def onset_events(grids: dict[str, Any], fps: int = FPS) -> list[dict[str, Any]]:
    """Cluster per-cell content transitions into visual entry events.

    ``grids`` maps a role to its dense ``[frames, rows, cols, 2]`` grid (mean
    opacity, premultiplied luma). A cell transition is a run of changing
    frames whose total change is at least ``MIN_CELL_CHANGE``; its onset is the
    first frame that completes half of that change (50% visible for fades,
    the midpoint for colour reveals inside an opaque card).
    """
    import numpy as np

    events: list[dict[str, Any]] = []
    for name, grid in grids.items():
        if EXCLUDED_ROLES.search(name) or len(grid) < 2:
            continue
        frames, rows, cols = grid.shape[:3]
        flat = grid.reshape(frames, rows * cols, 2).astype(np.int16)
        moving = np.abs(np.diff(flat, axis=0)).max(axis=2) > 2
        onsets: list[tuple[int, int]] = []
        for cell in np.nonzero(moving.any(axis=0))[0]:
            steps = moving[:, cell]
            index = 0
            while index < len(steps):
                if not steps[index]:
                    index += 1
                    continue
                stop = index
                while stop + 1 < len(steps) and steps[stop + 1]:
                    stop += 1
                before = flat[index, cell]
                total = int(np.abs(flat[stop + 1, cell] - before).max())
                if total >= MIN_CELL_CHANGE:
                    for frame in range(index + 1, stop + 2):
                        if np.abs(flat[frame, cell] - before).max() * 2 >= total:
                            onsets.append((frame, int(cell)))
                            break
                index = stop + 1
        onsets.sort()
        cluster: list[tuple[int, int]] = []
        for item in [*onsets, (10**9, -1)]:
            if cluster and item[0] - cluster[-1][0] > EVENT_GAP_FRAMES:
                if len(cluster) >= MIN_EVENT_CELLS:
                    onset = cluster[(len(cluster) - 1) // 2][0]
                    ys = [c // cols for _, c in cluster]
                    xs = [c % cols for _, c in cluster]
                    events.append(
                        {
                            "role": name,
                            "onset_frame": onset,
                            "onset_s": onset / fps,
                            "cells": len(cluster),
                            "cell_box": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
                        }
                    )
                cluster = []
            cluster.append(item)
    return sorted(events, key=lambda e: (e["onset_frame"], e["role"]))


def match_targets(targets: list[dict], events: list[dict]) -> list[dict[str, Any]]:
    """Pair each target with the unused event nearest its intended time."""
    used: set[int] = set()
    rows = []
    for target in sorted(targets, key=lambda t: t["speech_start"]):
        speech = float(target["speech_start"])
        intended = float(target.get("visible_start", speech))
        candidates = [
            (abs(event["onset_s"] - intended), i)
            for i, event in enumerate(events)
            if i not in used
            and MATCH_WINDOW[0] <= event["onset_s"] - speech <= MATCH_WINDOW[1]
        ]
        row = {**target, "event": None, "gap_s": None}
        if candidates:
            _, index = min(candidates)
            used.add(index)
            row["event"] = events[index]
            row["gap_s"] = round(events[index]["onset_s"] - speech, 3)
        rows.append(row)
    return rows


def dwell_seconds(timeline: list[dict], role: str, onset: int, fps: int) -> float:
    frames = 0
    for frame in timeline:
        if frame["n"] < onset:
            continue
        if frame.get("roles", {}).get(role, {}).get("peak", 0) < 0.5:
            break
        frames += 1
    return frames / fps


def animating_frames(timeline: list[dict[str, Any]]) -> set[int]:
    result: set[int] = set()
    previous: dict[str, Any] = {}
    for frame in timeline:
        current = {name: row["sig"] for name, row in overlay_roles(frame).items()}
        if previous and current != previous:
            result.add(int(frame["n"]))
        previous = current
    return result


def run(command: list[str]) -> str:
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{command[0]} failed: {done.stderr[-400:]}")
    return done.stdout + done.stderr


def stream_cfr(ffmpeg: str, path: Path, fps: int = FPS) -> dict[str, Any]:
    text = run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0"]
        + ["-c", "copy", "-f", "framecrc", "-"]
    )
    tb = re.search(r"#tb 0: (\d+)/(\d+)", text)
    rows = [
        [int(v) for v in line.split(",")[1:4]]
        for line in text.splitlines()
        if line and not line.startswith("#")
    ]
    if not tb or not rows:
        return {"pass": False, "reason": "no video packets"}
    base = int(tb.group(1)) / int(tb.group(2))
    durations = {row[2] for row in rows}
    pts = sorted(row[1] for row in rows)
    steps = {b - a for a, b in zip(pts, pts[1:], strict=False)}
    expected = round(1 / (fps * base))
    ok = durations == {expected} and steps <= {expected}
    return {
        "pass": ok,
        "frames": len(rows),
        "packet_durations": sorted(durations),
        "pts_steps": sorted(steps),
        "expected_step": expected,
        "fps": round(1 / (max(durations) * base), 3) if durations else None,
    }


def decoded_md5(ffmpeg: str, path: Path) -> list[str]:
    text = run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0"]
        + ["-f", "framemd5", "-"]
    )
    return [
        line.rsplit(",", 1)[1].strip()
        for line in text.splitlines()
        if line and not line.startswith("#")
    ]


def distinct_frames(ffmpeg: str, path: Path, scale: str | None = None) -> int:
    chain = (f"scale={scale}:flags=lanczos," if scale else "") + "mpdecimate"
    done = subprocess.run(
        [ffmpeg, "-nostdin", "-i", str(path), "-map", "0:v:0", "-vf", chain]
        + ["-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    found = re.findall(r"frame=\s*(\d+)", done.stderr)
    if done.returncode != 0 or not found:
        raise RuntimeError("mpdecimate failed: " + done.stderr[-300:])
    return int(found[-1])


def video_kbps(ffmpeg: str, path: Path) -> dict[str, Any]:
    done = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    line = next((x for x in done.stderr.splitlines() if "Video:" in x), "")
    size = re.search(r", (\d{2,5})x(\d{2,5})", line)
    rate = re.search(r"(\d+) kb/s", line)
    return {
        "width": int(size.group(1)) if size else None,
        "height": int(size.group(2)) if size else None,
        "kbps": int(rate.group(1)) if rate else None,
    }


def check(
    root: Path, preview: Path | None = None, ffmpeg: str = "ffmpeg"
) -> dict[str, Any]:
    payload = json.loads((root / "suite-input.json").read_text("utf-8"))
    config = payload["config"]
    render = root / "suite-render"
    timeline = read_timeline(render / "layers-timeline.jsonl")
    grids = load_grids(render / "layers-grid.npz", len(timeline))
    policy = config.get("sync_policy") or {}
    fps = int(policy.get("fps", FPS))
    events = onset_events(grids, fps)
    targets = policy.get("targets", [])
    matched = match_targets([t for t in targets if t["kind"] in GATED_KINDS], events)
    gaps = [row["gap_s"] for row in matched if row["gap_s"] is not None]
    sync: dict[str, Any] = {
        "policy": policy.get("version"),
        "targets": len(matched),
        "ungated_targets": len(targets) - len(matched),
        "matched": len(gaps),
        "median_s": round(statistics.median(gaps), 3) if gaps else None,
        "max_s": max(gaps) if gaps else None,
        "rows": matched,
    }
    low, high = SYNC_MEDIAN_RANGE_S
    sync["pass"] = bool(
        gaps
        and len(gaps) == len(matched)
        and low <= sync["median_s"] <= high
        and max(gaps) <= THRESHOLDS["sync_fail_s"]
    )
    sync["within_max"] = bool(gaps) and max(gaps) <= THRESHOLDS["sync_max_s"]
    dwell = [
        {
            "index": row["index"],
            "seconds": dwell_seconds(
                timeline, row["event"]["role"], row["event"]["onset_frame"], fps
            ),
        }
        for row in matched
        if row["kind"] == "material" and row["event"]
    ]
    final = render / "final.mp4"
    cfr = stream_cfr(ffmpeg, final, fps)
    md5 = decoded_md5(ffmpeg, final)
    moving = animating_frames(timeline)
    duplicates = [n for n in range(1, len(md5)) if md5[n] == md5[n - 1]]
    rendered_dups = [
        int(b["n"])
        for a, b in zip(timeline, timeline[1:], strict=False)
        if a["rgb"] == b["rgb"]
    ]
    dup = {
        "animating_frames": len(moving),
        "decoded_duplicates": len(duplicates),
        "duplicates_in_motion": sorted(set(duplicates) & moving),
        "rendered_duplicates_in_motion": sorted(set(rendered_dups) & moving),
    }
    dup["pass"] = (
        not dup["duplicates_in_motion"] and not dup["rendered_duplicates_in_motion"]
    )
    report: dict[str, Any] = {
        "version": "video-quality-check/1",
        "template_id": payload.get("template_id"),
        "timeline_frames": len(timeline),
        "sync": sync,
        "material_dwell": {
            "rows": dwell,
            "pass": all(
                row["seconds"] >= THRESHOLDS["material_dwell_s"] for row in dwell
            ),
        },
        "fps_cfr": cfr,
        "dup_in_motion": dup,
    }
    if preview is not None and preview.is_file():
        info = video_kbps(ffmpeg, preview)
        info["distinct_frames"] = distinct_frames(ffmpeg, preview)
        info["reference_distinct_frames"] = distinct_frames(
            ffmpeg, final, f"{info['width']}:{info['height']}"
        )
        info["frames"] = cfr.get("frames")
        allowed = THRESHOLDS["preview_extra_near_duplicates"] * (info["frames"] or 0)
        info["pass"] = (
            info["reference_distinct_frames"] - info["distinct_frames"] <= allowed
        )
        report["preview"] = info
    report["acceptance_phase1"] = bool(sync["pass"] and cfr["pass"] and dup["pass"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = check(args.root, args.preview, args.ffmpeg)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", "utf-8")
    summary = {
        "acceptance_phase1": report["acceptance_phase1"],
        "sync_median_s": report["sync"]["median_s"],
        "sync_max_s": report["sync"]["max_s"],
        "cfr": report["fps_cfr"]["pass"],
        "dup_in_motion": report["dup_in_motion"]["pass"],
        "preview": report.get("preview"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report["acceptance_phase1"] else 1


if __name__ == "__main__":
    sys.exit(main())
