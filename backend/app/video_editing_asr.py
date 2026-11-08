"""Cancellable local ASR subprocess. Accepts only the worker's fixed config."""

import argparse
from pathlib import Path

from .config import Settings
from .motion_library import atomic_json, read_json
from .video_editing_pipeline import transcribe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    args = parser.parse_args()
    root = args.instance.resolve()
    config = read_json(root / "asr-config.json")
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        video_editing_asr_provider=config.get("provider", "faster-whisper"),
        video_editing_asr_model=config["model"],
        video_editing_asr_device=config["device"],
    )
    result = transcribe(
        root / "input/speech.wav",
        read_json(root / "prepared.json"),
        settings,
        config.get("reference"),
        config.get("language", "zh"),
    )
    atomic_json(root / "transcript.json", result.model_dump(mode="json"))


if __name__ == "__main__":
    main()
