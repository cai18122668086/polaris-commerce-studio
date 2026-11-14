"""Bind independent body roles without imposing Apple's sequential card layout.

The recorded response, token clock, prompt and renderer bundle stay unchanged.
Existing plans accepted by the Apple bridge retain exactly that compilation;
only interleaved Bihuo body roles use the independent span bridge below.
"""

import re
from copy import deepcopy
from typing import Any

from .. import video_editing_apple_contracts as contracts
from ..video_editing_captioning import text_boundaries
from ..video_editing_contracts import Transcript


def _fit_capsule_captions(payload: dict, transcript: Transcript) -> dict:
    """Supply a missing display break using the frozen native font metrics.

    This only changes rendered lines, never the saved plan or source clock.
    """
    if payload.get("template_id") != "bihuo-02-v1":
        return payload
    from .registry import runtime

    native = runtime("bihuo-02-v1").capsule
    cfg = payload["config"]
    scale = cfg["size"][0] / 1080
    limit = 990 * scale
    positions = contracts._index(transcript)

    def width(line: dict) -> float:
        return sum(
            native.font(
                cfg["fonts"]["caption"],
                cfg.get("emphasis_size", 74) * scale
                if active
                else cfg.get("caption_size", 62) * scale,
            ).getlength(text)
            for text, active in native.approved_visual.caption_parts(line)
        )

    changed = []
    for cue in cfg["captions"]:
        lines = cue.get("lines", [{"text": cue["text"], "emphasis_spans": []}])
        if all(width(line) <= limit for line in lines):
            changed.append(cue)
            continue
        if len(lines) != 1:
            raise ValueError(
                "Capsule caption exceeds native capacity after explicit break"
            )
        line = lines[0]
        text = line["text"]
        if not cue.get("first_token_id") or not cue.get("last_token_id"):
            raise ValueError(
                "Capsule caption exceeds native capacity without recorded token bounds"
            )
        first, last = positions[cue["first_token_id"]], positions[cue["last_token_id"]]
        words = transcript.tokens[first : last + 1]
        if contracts._join([word.text for word in words]) != text:
            raise ValueError("Capsule caption text differs from its recorded tokens")
        safe, preferred = text_boundaries(text)
        emphasis = line.get("emphasis_spans", [])
        original_emphasis = [
            (positions[row["first_token_id"]], positions[row["last_token_id"]])
            for row in cue.get("emphasis_token_spans", [])
        ]
        candidates = []
        for stop in range(1, len(words)):
            cut = len(contracts._join([word.text for word in words[:stop]]))
            if cut not in safe or any(a < cut < b for a, b in emphasis):
                continue
            if any(a < first + stop <= b for a, b in original_emphasis):
                continue
            parts = []
            for begin, end in ((0, cut), (cut, len(text))):
                fragment = text[begin:end]
                if not re.search(r"\w", fragment):
                    break
                parts.append(
                    {
                        "text": fragment,
                        "emphasis_spans": [
                            [a - begin, b - begin]
                            for a, b in emphasis
                            if begin <= a < b <= end
                        ],
                    }
                )
            if len(parts) != 2:
                continue
            widths = [width(part) for part in parts]
            if max(widths) <= limit:
                candidates.append(
                    (
                        (
                            cut not in preferred,
                            max(widths),
                            abs(widths[0] - widths[1]),
                            cut,
                        ),
                        parts,
                    )
                )
        if not candidates:
            raise ValueError(
                "Capsule caption has no safe two-line native-capacity layout"
            )
        changed.append({**cue, "lines": min(candidates, key=lambda row: row[0])[1]})
    if any(a is not b for a, b in zip(changed, cfg["captions"], strict=True)):
        payload = {**payload, "config": {**cfg, "captions": changed}}
    # Exercise the actual native painter now; do not defer capacity errors to
    # the subprocess after source preparation and a long video render.
    for cue in payload["config"]["captions"]:
        native.caption(payload["config"], sum(cue["time"]) / 2)
    return payload


def verify_plan(
    raw: dict[str, Any],
    transcript: Transcript,
    cards: list[dict[str, Any]],
    *,
    require_semantic_captions: bool = False,
    allow_mixed_body: bool = True,
) -> dict[str, Any]:
    original = contracts.AppleSuitePlan.model_validate(raw)
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
    # A conclusion already displays its spoken phrase. An optional feature
    # wholly repeated inside it must not start another body card after closing.
    # Check every original span/order first, including any suppressed duplicate.
    positions = contracts._index(transcript)
    prior = contracts._at(original.opening.intro_last_token_id, positions)
    closing = (
        [
            contracts._span(row, transcript, positions, 32)
            for row in (original.conclusion.first, original.conclusion.second)
        ]
        if original.conclusion
        else []
    )
    kept = []
    suppressed = []
    for row in original.features:
        span = contracts._span(row, transcript, positions, 20)
        if span["first"] <= prior:
            raise ValueError("Feature phrases must follow source order after opening")
        prior = span["last"]
        if any(
            end["first"] <= span["first"] <= span["last"] <= end["last"]
            for end in closing
        ):
            suppressed.append(row)
        else:
            kept.append(row.model_dump(mode="json"))
    features["features"] = kept
    features.update(points=[], materials=[])
    checked = contracts.verify_plan(
        features,
        transcript,
        cards,
        require_semantic_captions=require_semantic_captions,
        allow_mixed_body=True,
    )
    result["features"] = checked["features"]
    if suppressed:
        notice = "结尾中的重复功能标签已省略，原话保留在结尾与字幕。"
        # Keep the strict warning array capacity even for a full provider list.
        if len(result["warnings"]) < 12:
            result["warnings"].append(notice)
        else:
            result["warnings"][-1] = (
                result["warnings"][-1][: 299 - len(notice)] + "；" + notice
            )
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

    def fitted_recipe(resolved: dict, **options: Any) -> dict:
        return _fit_capsule_captions(recipe_compiler(resolved, **options), transcript)

    cards = [{**asset, "id": ident} for ident, asset in asset_files.items()]
    verified = verify_plan(plan, transcript, cards)
    kwargs: dict[str, Any] = dict(
        creative_options=creative_options,
        music=music,
        ffmpeg=ffmpeg,
        size=size,
        recipe_compiler=fitted_recipe,
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
        return fitted_recipe({**resolved, "features": features}, **options)

    kwargs["recipe_compiler"] = independent_roles
    return contracts.compile_render_input(
        {**verified, "features": []},
        transcript,
        asset_files,
        source_path,
        fonts,
        **kwargs,
    )
