"""Local speech-to-text for benchmark posts the supplier cannot transcribe (小红书).

Runs as a subprocess (`python -m app.video_benchmark_asr <media-url> <workdir>`)
so the model never loads into the API process. Prints one JSON object:
{"text": ..., "segments": [{"start", "end", "text"}], "duration_seconds": ...}.
No paid call; the media URL is a signed CDN link already validated by host.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .video_benchmark_platforms import MAX_DURATION_SECONDS, MEDIA_HOST_SUFFIXES

MAX_BYTES = 150 * 1024 * 1024


class AsrFailure(Exception):
    pass


def download(url: str, target: Path) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != "https" or not host.endswith(MEDIA_HOST_SUFFIXES):
        raise AsrFailure("media_host_not_allowed")
    received = 0
    with httpx.stream(
        "GET",
        url,
        timeout=httpx.Timeout(60, connect=10),
        follow_redirects=False,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/",
        },
    ) as response:
        if response.status_code != 200:
            raise AsrFailure(f"media_http_{response.status_code}")
        with target.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 16):
                received += len(chunk)
                if received > MAX_BYTES:
                    raise AsrFailure("media_too_large")
                handle.write(chunk)


def transcribe(media_url: str, workdir: Path, settings: Settings) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    video, audio = workdir / "source.mp4", workdir / "audio.wav"
    download(media_url, video)
    ffmpeg = (
        settings.video_editing_ffmpeg
        if hasattr(settings, "video_editing_ffmpeg")
        else "ffmpeg"
    )
    done = subprocess.run(
        [
            str(ffmpeg or "ffmpeg"),
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-t",
            str(MAX_DURATION_SECONDS),
            "-f",
            "wav",
            str(audio),
        ],
        capture_output=True,
        timeout=180,
    )
    if done.returncode != 0 or not audio.is_file() or audio.stat().st_size < 3200:
        raise AsrFailure("audio_decode_failed")
    video.unlink(missing_ok=True)
    duration = (audio.stat().st_size - 44) / 32000
    root = Path(settings.video_editing_asr_model)
    if (root / "paraformer").is_dir():
        from funasr import AutoModel

        model = AutoModel(
            model=str(root / "paraformer"),
            vad_model=str(root / "vad"),
            punc_model=str(root / "punc"),
            device=settings.video_editing_asr_device,
            ncpu=4,
            disable_update=True,
            trust_remote_code=False,
        )
        result = model.generate(
            input=str(audio), sentence_timestamp=True, batch_size_s=60
        )
        row = result[0] if isinstance(result, list) and result else {}
        text = str(row.get("text") or "").replace(" ", "")
        segments = [
            {
                "start": s["start"] / 1000,
                "end": s["end"] / 1000,
                "text": str(s.get("text", "")).replace(" ", ""),
            }
            for s in row.get("sentence_info") or []
            if isinstance(s, dict)
            and isinstance(s.get("start"), (int, float))
            and isinstance(s.get("end"), (int, float))
        ]
    else:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            settings.video_editing_asr_model,
            device=settings.video_editing_asr_device,
            compute_type="int8"
            if settings.video_editing_asr_device == "cpu"
            else "float16",
            cpu_threads=4,
        )
        parts, _ = model.transcribe(
            str(audio),
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt="以下是普通话口播，请使用简体中文并加标点。",
        )
        segments = [
            {"start": p.start, "end": p.end, "text": p.text.strip()}
            for p in parts
            if p.text.strip()
        ]
        text = "".join(
            s["text"] if s["text"][-1:] in "。！？，" else s["text"] + "，"
            for s in segments
        ).rstrip("，") + ("。" if segments else "")
    audio.unlink(missing_ok=True)
    segments = [
        s
        for s in segments
        if math.isfinite(s["start"])
        and math.isfinite(s["end"])
        and s["end"] >= s["start"] >= 0
    ]
    return {
        "text": text.strip(),
        "segments": segments,
        "duration_seconds": round(duration, 2),
    }


def main() -> None:
    media_url, workdir = sys.argv[1], Path(sys.argv[2])
    try:
        payload = transcribe(media_url, workdir, Settings())
    except AsrFailure as error:
        payload = {"error": str(error)}
    except Exception as error:  # noqa: BLE001 - one JSON line either way
        payload = {"error": "asr_failed:" + type(error).__name__}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
