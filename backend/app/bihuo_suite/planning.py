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
        if "".join(word.text for word in words) != text:
            raise ValueError("Capsule caption text differs from its recorded tokens")
        safe, preferred = text_boundaries(text)
        emphasis = line.get("emphasis_spans", [])
        original_emphasis = [
            (positions[row["first_token_id"]], positions[row["last_token_id"]])
            for row in cue.get("emphasis_token_spans", [])
        ]
        candidates = []
        for stop in range(1, len(words)):
            cut = len("".join(word.text for word in words[:stop]))
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


def native_caption_text(resolved: dict, plan: dict, transcript: Transcript) -> dict:
    """Use the native recipes' exact concatenation of recorded FA token text.

    Apple inserts visual separators between adjacent ASCII tokens. Bihuo's
    glyph clocks require the original token characters, including source spaces
    but excluding those synthetic separators. Rebind highlight offsets too.
    """
    positions = contracts._index(transcript)
    cues = {
        (cue["first_token_id"], cue["last_token_id"]): cue
        for cue in plan.get("captions") or []
    }
    captions = []
    changed = False
    for row in resolved.get("captions", []):
        cue = cues.get((row.get("first_token_id"), row.get("last_token_id")))
        if cue is None:
            captions.append(row)
            continue
        first, last = positions[cue["first_token_id"]], positions[cue["last_token_id"]]
        words = transcript.tokens
        text = "".join(word.text for word in words[first : last + 1])
        if (
            row["text"] == text
            and "".join(line["text"] for line in row["lines"]) == text
        ):
            captions.append(row)
            continue
        cut = (
            positions[cue["line_break_after_token_id"]]
            if cue.get("line_break_after_token_id")
            else None
        )
        segments = [(first, last)] if cut is None else [(first, cut), (cut + 1, last)]
        lines = []
        for (a, b), previous in zip(segments, row["lines"], strict=True):
            joined = ""
            line = ""
            offsets = [0]
            for word in words[a : b + 1]:
                if (
                    joined
                    and word.text
                    and re.search(r"[A-Za-z0-9]$", joined)
                    and re.match(r"^[A-Za-z0-9]", word.text)
                ):
                    joined += " "
                    offsets.append(len(line))
                for char in word.text:
                    joined += char
                    line += char
                    offsets.append(len(line))
            if joined != previous["text"]:
                raise ValueError(
                    "Caption display differs from its recorded word binding"
                )
            # Preserve the already reduced accent choices, rather than restoring
            # every provider-selected highlight after sparse emphasis fitting.
            ranges = [
                [offsets[start], offsets[stop]]
                for start, stop in previous["emphasis_spans"]
            ]
            lines.append({**previous, "text": line, "emphasis_spans": ranges})
        captions.append(
            {
                **row,
                "text": text,
                "lines": lines,
                "emphasis": " ".join(
                    line["text"][a:b]
                    for line in lines
                    for a, b in line["emphasis_spans"]
                ),
            }
        )
        changed = True
    return {**resolved, "captions": captions} if changed else resolved


def fit_recorded_display_spans(raw: dict, transcript: Transcript) -> dict:
    """Fit optional display labels and missing line breaks, never speech spans.

    The provider capture remains immutable. Every display change binds to an
    existing token and is checked again by the unchanged strict contract.
    """
    plan = contracts.AppleSuitePlan.model_validate(raw)
    positions = contracts._index(transcript)
    words = transcript.tokens
    source_text = "".join(word.text for word in words)
    safe, preferred = text_boundaries(source_text)
    offsets = [0]
    for word in words:
        offsets.append(offsets[-1] + len(word.text))
    changed = deepcopy(raw)
    edits = False
    for cue, output in zip(
        plan.captions or [], changed.get("captions") or [], strict=True
    ):
        first = contracts._at(cue.first_token_id, positions)
        last = contracts._at(cue.last_token_id, positions)
        text = contracts._join([word.text for word in words[first : last + 1]])
        if cue.line_break_after_token_id or len(re.findall(r"\w", text)) <= 18:
            continue
        emphasis = [
            (
                contracts._at(row.first_token_id, positions),
                contracts._at(row.last_token_id, positions),
            )
            for row in cue.emphasis
        ]
        candidates = []
        for cut in range(first, last):
            if offsets[cut + 1] not in safe or any(a <= cut < b for a, b in emphasis):
                continue
            lines = [
                contracts._join([word.text for word in words[a : b + 1]])
                for a, b in ((first, cut), (cut + 1, last))
            ]
            sizes = [len(re.findall(r"\w", line)) for line in lines]
            if all(0 < size <= 18 for size in sizes):
                candidates.append(
                    (
                        (
                            offsets[cut + 1] not in preferred,
                            max(sizes),
                            abs(sizes[0] - sizes[1]),
                            cut,
                        ),
                        cut,
                    )
                )
        if candidates:
            output["line_break_after_token_id"] = words[min(candidates)[1]].id
            edits = True
    for chapter, output in zip(plan.chapters, changed.get("chapters", []), strict=True):
        # A chapter is a short navigation label, not a second transcript. Keep
        # the first complete recorded clause; all words remain in the captions.
        first = contracts._at(chapter.first_token_id, positions)
        last = contracts._at(chapter.last_token_id, positions)
        text = contracts._join([word.text for word in words[first : last + 1]])
        if len(text) <= 22 or first > last:
            continue
        for cut in range(first, last):
            label = contracts._join([word.text for word in words[first : cut + 1]])
            if len(label) > 22:
                break
            if (
                re.search(r"[，。！？；、,!?;]$", label)
                and offsets[cut + 1] in safe
                and re.search(r"\w", label)
            ):
                output["last_token_id"] = words[cut].id
                edits = True
                break
    if edits:
        notice = "字幕分行与章节标签已按原词边界适配，口播内容和时间保持不变。"
        warnings = changed.setdefault("warnings", [])
        if len(warnings) < 12:
            warnings.append(notice)
        else:
            warnings[-1] = warnings[-1][: 299 - len(notice)] + "；" + notice
        return changed
    return raw


def verify_plan(
    raw: dict[str, Any],
    transcript: Transcript,
    cards: list[dict[str, Any]],
    *,
    require_semantic_captions: bool = False,
    allow_mixed_body: bool = True,
) -> dict[str, Any]:
    raw = fit_recorded_display_spans(raw, transcript)
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
        from .conditional_layout import prepare

        return prepare(
            _fit_capsule_captions(
                recipe_compiler(
                    native_caption_text(resolved, verified, transcript), **options
                ),
                transcript,
            )
        )

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
