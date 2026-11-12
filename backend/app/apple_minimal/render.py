"""Execute complete recipes with one raw voice clock; no model calls while rendering."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image

from . import (
    information as apple_information,
)
from . import (
    media as apple_media,
)
from . import (
    visual as apple_visual,
)


def sha(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def render(cfg: dict[str, Any], out: str | Path) -> dict[str, Any]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    W, H = cfg["size"]
    fps = cfg.get("fps", 25)
    frames = round(cfg["duration"] * fps)
    ff = cfg.get("ffmpeg", "ffmpeg")
    start = time.monotonic()
    files = {
        Path(__file__),
        Path(apple_visual.__file__),
        Path(apple_media.__file__),
        Path(apple_information.__file__),
        Path(__file__).with_name("pilot.py"),
    }
    code = {path.name: sha(path) for path in files}
    (out / "input-snapshot.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf8"
    )
    (out / "code-sha256.json").write_text(json.dumps(code, indent=2), encoding="utf8")
    for name in code:
        (out / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    dec = subprocess.Popen(
        [
            ff,
            "-v",
            "error",
            "-ss",
            str(cfg.get("source_in", 0)),
            "-i",
            cfg["source"],
            "-vf",
            f"scale={W}:{H},fps={fps}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    enc = subprocess.Popen(
        [
            ff,
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{W}x{H}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(out / "silent.mp4"),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert dec.stdout is not None
    assert enc.stdin is not None and enc.stderr is not None
    checks = []
    last = None
    keyframes = set(cfg.get("evidence_frames", [])) | {0, frames - 1}
    try:
        for n in range(frames):
            data = dec.stdout.read(W * H * 3)
            if len(data) != W * H * 3:
                if cfg.get("source_end_policy") != "hold" or last is None:
                    raise ValueError("Raw source shorter than declared voice timeline")
            else:
                last = Image.frombytes("RGB", (W, H), data)
            visual = apple_visual.render("V02", last, n, cfg)
            layers = {"background": visual["background"]}
            for media in cfg.get("media", []):
                local = n - round(media["start"] * fps)
                if (
                    round(media.get("render_from", media["start"]) * fps)
                    <= n
                    <= round(media["end"] * fps)
                ):
                    layers.update(
                        apple_media.render(
                            "V03",
                            last,
                            local,
                            {**media["input"], "size": [W, H], "fps": fps},
                        )
                    )
            layers["presenter"] = visual["presenter"]
            layers.update(apple_visual.render_subtitle("T01", n, cfg))
            for info in cfg.get("information", []):
                if info["start"] <= n / fps < info["end"]:
                    layers.update(
                        {
                            f"{info['component']}-{k}": v
                            for k, v in apple_information.render_subtitle(
                                info["component"],
                                n - round(info["start"] * fps),
                                {**info["input"], "size": [W, H], "fps": fps},
                            ).items()
                        }
                    )
            layers.update(apple_visual.render_subtitle("T05", n, cfg))
            canvas = Image.new("RGBA", (W, H))
            role_boxes = {}
            for name, layer in layers.items():
                canvas.alpha_composite(layer)
                role_boxes[name] = layer.getchannel("A").getbbox()
            checks.append(
                {
                    "frame": n,
                    "presenterAlphaBox": role_boxes["presenter"],
                    "textVisible": any(
                        v is not None
                        for k, v in role_boxes.items()
                        if k in {"main", "support", "caption"} or k.startswith("T")
                    ),
                    "roleBounds": role_boxes,
                }
            )
            if n in keyframes:
                folder = out / "evidence"
                folder.mkdir(exist_ok=True)
                canvas.convert("RGB").save(folder / f"frame-{n:05}.jpg", quality=93)
                folder = out / "roles" / f"{n:05}"
                folder.mkdir(parents=True, exist_ok=True)
                for name, layer in layers.items():
                    if name not in {"background", "presenter"}:
                        layer.save(folder / f"{name}.png")
            enc.stdin.write(canvas.convert("RGB").tobytes())
            if n % 100 == 0:
                print(
                    f"{out.name} {n}/{frames} {time.monotonic() - start:.1f}s",
                    flush=True,
                )
        enc.stdin.close()
        err = enc.stderr.read().decode()
        code_exit = enc.wait()
        if code_exit:
            raise RuntimeError(err)
    except BaseException:
        if enc.poll() is None:
            enc.kill()
            enc.wait()
        raise
    finally:
        dec.terminate()
        dec.wait()
        apple_media.clear_cache()
    final = out / "final.mp4"
    subprocess.run(
        [
            ff,
            "-v",
            "error",
            "-i",
            str(out / "silent.mp4"),
            "-ss",
            str(cfg.get("source_in", 0)),
            "-i",
            cfg["source"],
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            str(frames / fps),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            "apad",
            "-movflags",
            "+faststart",
            "-y",
            str(final),
        ],
        check=True,
    )
    subprocess.run(
        [ff, "-v", "error", "-xerror", "-i", str(final), "-f", "null", "-"], check=True
    )
    (out / "frame-measurements.json").write_text(
        json.dumps(checks, ensure_ascii=False), encoding="utf8"
    )
    receipt = {
        "engine": "apple-minimal-suite",
        "frames": frames,
        "width": W,
        "height": H,
        "fps": fps,
        "duration_seconds": frames / fps,
        "source_sha256": sha(cfg["source"]),
        "input_sha256": sha(out / "input-snapshot.json"),
        "source_code": code,
        "final_sha256": sha(final),
        "full_decode": "passed",
        "voice_clock": "unretimed source",
        "original_media_audio": "muted",
        "audio": "source voice; BGM/FX not yet reconstructed",
        "wall_seconds": round(time.monotonic() - start, 2),
        "visual_status": "candidate: complete mechanism review required",
    }
    (out / "render-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(str(final), flush=True)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    render(json.loads(a.input.read_text(encoding="utf8")), a.output)
