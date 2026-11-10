"""Keep the original picture clock and stereo buses in native episode composition."""

import importlib
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .motion_library import atomic_json, read_json, sha256
from .video_editing_audio_verification import MAX_SOURCE_AUDIO_OFFSET_SAMPLES, RATE
from .video_editing_source_aspect import (
    SOURCE_ASPECT_DESIGN,
    SOURCE_ASPECT_RECEIPT,
    fit_source_picture,
    source_aspect_scene,
)

_EPISODE_SHA256 = "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038"
_VOICE = ",asplit=2[voice][voice_stem]"
_MUSIC = ",asplit=2[bgm_bus][bgm_stem]"
_MIXED = "[mixed]"
_STEREO = ",aformat=channel_layouts=stereo"
_VOICE_CLOCK = re.compile(
    rf"^\[0:a\]atrim=start=0(?:\.0+)?:duration=[\d.]+,"
    rf"asetpts=PTS-STARTPTS,aresample={RATE},",
    re.MULTILINE,
)


def stereo_composition_graph(graph: str, offset_samples: int = 0) -> str:
    if (
        graph.count(_VOICE) != 1
        or graph.count(_MUSIC) > 1
        or not graph.endswith(_MIXED)
    ):
        raise ValueError("Pinned native audio filter graph changed")
    if offset_samples:
        move = (
            f"adelay={offset_samples}S:all=1"
            if offset_samples > 0
            else f"atrim=start_sample={-offset_samples},asetpts=PTS-STARTPTS"
        )
        graph, changed = re.subn(
            _VOICE_CLOCK,
            f"[0:a]asetpts=PTS-STARTPTS,aresample={RATE},{move},",
            graph,
        )
        if changed != 1:
            raise ValueError("Pinned native narration clock filter changed")
    return (
        graph.removesuffix(_MIXED)
        .replace(_VOICE, _STEREO + _VOICE)
        .replace(_MUSIC, _STEREO + _MUSIC)
        + _STEREO
        + _MIXED
    )


def install_native_stereo_composition(package: Path, root: Path) -> None:
    """Adapt the pinned original episode composition within this task process."""
    path = package / "commercial_runtime/episode.py"
    if sha256(path) != _EPISODE_SHA256:
        raise ValueError("Native stereo composition needs the pinned episode exporter")
    sys.path.insert(0, str(package))
    try:
        episode: Any = importlib.import_module("commercial_runtime.episode")
    finally:
        sys.path.pop(0)
    if Path(episode.__file__).resolve() != path:
        raise ValueError(
            "Native stereo composition resolved the wrong episode exporter"
        )
    prepared = root / "prepared.json"
    clock = read_json(prepared)["clock"] if prepared.is_file() else {}
    offset_samples = clock.get("audio_offset_samples", 0)
    if (
        type(offset_samples) is not int
        or abs(offset_samples) > MAX_SOURCE_AUDIO_OFFSET_SAMPLES
        or (offset_samples < 0 and not clock.get("silent_head"))
    ):
        raise ValueError("Native narration origin needs its measured clock")

    plan_path = root / "episode.json"
    plan = read_json(plan_path) if plan_path.is_file() else {}
    source_canvas = None
    if plan.get("design", {}).get("id") == SOURCE_ASPECT_DESIGN:
        scenes: Any = importlib.import_module("commercial_runtime.scene_composer")

        def source_scene(data: dict, instance: Path) -> list:
            if (
                Path(instance).resolve() != root
                or data["design"]["id"] != SOURCE_ASPECT_DESIGN
                or data["visual_scenes"]
                != [source_aspect_scene(data["source"]["duration_seconds"])]
                or data["shots"]
                or data.get("visual_overlays")
                or Path(data["source"]["path"]).resolve() != root / "input/source.mp4"
            ):
                raise ValueError(
                    "Source aspect composition needs an unadorned source scene"
                )
            # The original compositing command already has this source track.
            return []

        scenes.render = source_scene
        source_canvas = {key: plan["output"][key] for key in ("width", "height")}

    def run(command: list[str], *args: Any, **kwargs: Any) -> Any:
        if (
            command[0] == "ffmpeg"
            and "-filter_complex" in command
            and _MIXED in command
        ):
            index = command.index("-filter_complex") + 1
            graph = root / "plans/composition.ffgraph"
            if (
                str(root / "outputs/episode.mp4") not in command
                or graph.read_text(encoding="utf-8") != command[index]
            ):
                raise ValueError(
                    "Native stereo composition target differs from its task"
                )
            before = sha256(graph)
            command = command.copy()
            command[index] = stereo_composition_graph(command[index], offset_samples)
            if source_canvas is not None:
                command[index] = fit_source_picture(command[index], **source_canvas)
            graph.write_text(command[index], encoding="utf-8")
            if source_canvas is not None:
                atomic_json(
                    root / SOURCE_ASPECT_RECEIPT,
                    {
                        "policy": "contain",
                        "canvas": source_canvas,
                        "composition_sha256": sha256(graph),
                    },
                )
            atomic_json(
                root / "compatibility/stereo-composition.json",
                {
                    "version": "tengli.native-stereo-mix/1",
                    "original_graph_sha256": before,
                    "applied_graph_sha256": sha256(graph),
                    "channel_layout": "stereo",
                    "source_audio_offset_samples": offset_samples,
                },
            )
        return subprocess.run(command, *args, **kwargs)

    episode.subprocess = SimpleNamespace(run=run)
