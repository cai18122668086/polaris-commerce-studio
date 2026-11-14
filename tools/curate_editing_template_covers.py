"""Review existing encoded examples, then install explicitly chosen stable covers.

No model, recognition, planning or full-video rendering is performed. Candidate
sampling is only a review aid: installation requires a source-hash-bound choice
and a written reason for every cover. Existing example videos remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bound(root: Path, row: dict) -> Path:
    path = (root / row["file"]).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or digest(path) != row["sha256"]:
        raise ValueError("Example missing, changed or outside store")
    return path


def frame(ffmpeg: str, path: Path, seconds: float, width: int) -> bytes:
    return subprocess.check_output(
        [ffmpeg, "-v", "error", "-threads", "1", "-ss", str(seconds), "-i", str(path),
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2", "-threads", "1",
         "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    )


def entries(manifest: dict) -> list[tuple[str, str, dict]]:
    rows = [("examples", tid, value) for tid, value in manifest["examples"].items()]
    rows.extend(("style_previews", tid, value) for tid, value in manifest.get("style_previews", {}).items() if tid not in manifest["examples"])
    return rows


def candidates(root: Path, output: Path, ffmpeg: str, manifest: dict) -> None:
    output.mkdir(parents=True, exist_ok=False)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17) if Path("C:/Windows/Fonts/msyh.ttc").exists() else ImageFont.load_default(size=17)

    def sample(row: tuple[str, str, dict]) -> dict:
        collection, tid, entry = row
        video = bound(root, entry["video"])
        info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace").stderr
        clock = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
        if not clock:
            raise ValueError("Cannot read example duration")
        duration = int(clock[1]) * 3600 + int(clock[2]) * 60 + float(clock[3])
        times = [round(min(duration - .1, t), 3) for t in [.9, duration * .28, duration * .5, duration * .72]]
        canvas = Image.new("RGB", (1000, 410), "#f4f5f7")
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 3), tid, font=font, fill="#20252d")
        poster = bound(root, entry["poster"]) if entry.get("poster") else None
        for i, time in enumerate([None, *times]):
            raw = poster.read_bytes() if time is None and poster else frame(ffmpeg, video, time or 0, 180)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((180, 340))
            canvas.paste(im, (i * 200 + (200 - im.width) // 2, 35 + (340 - im.height) // 2))
            draw.text((i * 200 + 8, 380), "当前封面" if time is None else f"{time:.3f}s", font=font, fill="#464d59")
        canvas.save(output / (tid + ".jpg"), quality=90)
        return {"id": tid, "collection": collection, "source_sha256": entry["video"]["sha256"], "duration": duration, "candidate_seconds": times}

    with ThreadPoolExecutor(max_workers=3) as executor:
        rows = list(executor.map(sample, entries(manifest)))
    for start in range(0, len(rows), 5):
        sheet = Image.new("RGB", (1000, 410 * len(rows[start:start + 5])), "white")
        for i, row in enumerate(rows[start:start + 5]):
            with Image.open(output / (row["id"] + ".jpg")) as im:
                sheet.paste(im, (0, i * 410))
        sheet.save(output / f"sheet-{start // 5 + 1:02d}.jpg", quality=90)
    (output / "candidates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": "ready_for_visual_review", "templates": len(rows), "model_calls": 0, "output": str(output)}))


def install(root: Path, output: Path, ffmpeg: str, manifest: dict, choices: Path) -> None:
    selections = json.loads(choices.read_text("utf-8"))
    rows = {tid: (collection, entry) for collection, tid, entry in entries(manifest)}
    if set(selections) != set(rows):
        raise ValueError("Every visible template needs one reviewed cover choice")
    # Validate all choices before creating a store.
    for tid, choice in selections.items():
        _, entry = rows[tid]
        if choice["source_sha256"] != entry["video"]["sha256"] or not choice["reason"].strip():
            raise ValueError("Cover choice needs the exact source hash and review reason")
        if not isinstance(choice["seconds"], (int, float)) or not 0 <= choice["seconds"] < float("inf"):
            raise ValueError("Cover time must be finite and nonnegative")
        bound(root, entry["video"])
    output.mkdir(parents=True, exist_ok=False)
    for collection in ("examples", "style_previews"):
        for entry in manifest.get(collection, {}).values():
            for kind in ("video", "poster"):
                if kind not in entry:
                    continue
                source = bound(root, entry[kind])
                target = output / source.relative_to(root.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    try:
                        target.hardlink_to(source)
                    except OSError:
                        shutil.copy2(source, target)
    receipt = []
    for tid, choice in selections.items():
        collection, entry = rows[tid]
        source = bound(root, entry["video"])
        previous = entry.get("cover_review", {})
        if all(previous.get(key) == value for key, value in choice.items()):
            receipt.append({"id": tid, "collection": collection, **previous, "poster": entry["poster"]})
            continue
        data = frame(ffmpeg, source, choice["seconds"], 540)
        with Image.open(io.BytesIO(data)) as im:
            if im.width * 16 != im.height * 9:
                raise ValueError("Template cover must preserve the complete portrait frame")
        target = output / f"curated-{tid}-{hashlib.sha256(data).hexdigest()[:12]}.jpg"
        target.write_bytes(data)
        entry["poster"] = {"file": target.name, "sha256": digest(target)}
        entry["cover_review"] = {**choice, "method": "explicitly_reviewed_encoded_example_frame", "width": 540, "height": 960}
        manifest[collection][tid] = entry
        receipt.append({"id": tid, "collection": collection, **entry["cover_review"], "poster": entry["poster"]})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "cover-review-receipt.json").write_text(json.dumps({"status": "passed", "covers": receipt, "model_calls": 0, "new_video_encodes": 0}, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": "passed", "reviewed_covers": len(receipt), "output": str(output)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--selections", type=Path)
    args = parser.parse_args()
    if not args.ffmpeg:
        import imageio_ffmpeg
        args.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    root = args.examples.resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    if args.selections:
        install(root, args.output, args.ffmpeg, manifest, args.selections)
    else:
        candidates(root, args.output, args.ffmpeg, manifest)


if __name__ == "__main__":
    main()
