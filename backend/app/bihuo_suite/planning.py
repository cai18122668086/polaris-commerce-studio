"""Bind independent body roles without imposing Apple's sequential card layout.

The recorded response, token clock, prompt and renderer bundle stay unchanged.
Existing plans accepted by the Apple bridge retain exactly that compilation;
only interleaved Bihuo body roles use the independent span bridge below.
"""

from copy import deepcopy
from typing import Any

from .. import video_editing_apple_contracts as contracts
from ..video_editing_contracts import Transcript


def verify_plan(
    raw: dict[str, Any],
    transcript: Transcript,
    cards: list[dict[str, Any]],
    *,
    require_semantic_captions: bool = False,
    allow_mixed_body: bool = True,
) -> dict[str, Any]:
    # Validate each sequence with the unchanged strict word/schema/caption
    # checks. They may interleave with each other, never reorder internally.
    body = deepcopy(raw)
    body["features"] = []
    result = contracts.verify_plan(
        body,
        transcript,
        cards,
        require_semantic_captions=require_semantic_captions,
        allow_mixed_body=True,
    )
    features = deepcopy(raw)
    features.update(points=[], materials=[])
    checked = contracts.verify_plan(
        features,
        transcript,
        cards,
        require_semantic_captions=require_semantic_captions,
        allow_mixed_body=True,
    )
    result["features"] = checked["features"]
    return result


def compile_render_input(
    plan: dict[str, Any],
    transcript: Transcript,
    asset_files: dict[str, dict[str, Any]],
    source_path: str,
    fonts: dict[str, str],
    *,
    creative_options: dict[str, Any] | None = None,
    music: str = "template",
    ffmpeg: str = "ffmpeg",
    size: tuple[int, int] = (1080, 1920),
    recipe_compiler: Any = None,
) -> dict[str, Any]:
    if recipe_compiler is None:
        raise ValueError("Bihuo compilation requires its selected recipe compiler")
    cards = [{**asset, "id": ident} for ident, asset in asset_files.items()]
    verified = verify_plan(plan, transcript, cards)
    kwargs = dict(
        creative_options=creative_options,
        music=music,
        ffmpeg=ffmpeg,
        size=size,
        recipe_compiler=recipe_compiler,
    )
    try:
        contracts.verify_plan(verified, transcript, cards, allow_mixed_body=True)
    except ValueError as error:
        if str(error) not in {
            "Body phrases must follow source order before the quote",
            "Feature cards must follow material playback",
        }:
            raise
    else:
        # Keep already-valid frozen plans byte-for-byte compatible.
        return contracts.compile_render_input(
            verified, transcript, asset_files, source_path, fonts, **kwargs
        )

    positions = contracts._index(transcript)
    features = []
    for row in verified["features"]:
        span = contracts._span(
            contracts.AppleSpan.model_validate(row), transcript, positions, 20
        )
        features.append({k: v for k, v in span.items() if k not in {"first", "last"}})

    def independent_roles(resolved: dict, **options: Any) -> dict:
        # The normal resolver still binds all captions, materials and points.
        # Feature times come from the same actual source tokens, without moves.
        return recipe_compiler({**resolved, "features": features}, **options)

    kwargs["recipe_compiler"] = independent_roles
    return contracts.compile_render_input(
        {**verified, "features": []},
        transcript,
        asset_files,
        source_path,
        fonts,
        **kwargs,
    )
