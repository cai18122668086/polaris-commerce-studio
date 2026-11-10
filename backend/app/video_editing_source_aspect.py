"""Use the pinned native episode's continuous source for basic subtitles."""

from typing import Any

SOURCE_ASPECT_DESIGN = "tengli-source-aspect-subtitles-v1"
SOURCE_ASPECT_RECEIPT = "compatibility/source-aspect.json"
SQUARE_PIXEL_RATIOS = frozenset({None, "N/A", "0:1", "1:1"})


def source_aspect_scene(duration: float) -> dict[str, Any]:
    return {
        "id": "source-aspect",
        "start_seconds": 0,
        "end_seconds": duration,
        "background": {"mode": "source", "fit": "contain"},
        "layers": [],
    }


def fit_source_picture(graph: str, width: int, height: int) -> str:
    picture, separator, remaining = graph.partition(";")
    size = f"{width}:{height}"
    native = f"scale={size}:force_original_aspect_ratio=increase,crop={size}"
    if (
        not separator
        or not picture.startswith("[0:v]trim=")
        or picture.count(native) != 1
    ):
        raise ValueError("Pinned native source picture filter changed")
    fit = (
        f"scale={size}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={size}:(ow-iw)/2:(oh-ih)/2"
    )
    return picture.replace(native, fit, 1) + separator + remaining
