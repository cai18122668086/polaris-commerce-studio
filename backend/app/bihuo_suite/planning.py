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
from . import frame_policy as framing
from . import info_card
from . import sync_policy as sync

CAPTION_LINES = "bihuo-caption-lines/1"
# A line with at most this many word characters next to a longer one is an
# orphan ("质地" over "清爽不黏腻，") when the whole caption fits on one line.
ORPHAN_CHARS = 2
CAPSULE_ENDING = "bihuo-capsule-ending/1"


def _merged_line(lines: list[dict]) -> dict:
    first, second = lines
    shift = len(first["text"])
    return {
        **first,
        "text": first["text"] + second["text"],
        "emphasis_spans": [list(span) for span in first.get("emphasis_spans", [])]
        + [[a + shift, b + shift] for a, b in second.get("emphasis_spans", [])],
    }


def _hold_capsule_card(payload: dict) -> dict:
    """Keep bihuo-02's information card up to the last frame when nothing follows.

    Without a closing quote the bundle exits the card over the last 0.36 s and
    schedules its closing card at the clip end, i.e. after the last frame: the
    card grows past the side margins while fading and the final frame is empty
    apart from the presenter circle (acceptance 2026-11-26, ACCEPT-39 #5).
    Only in that case the card exit moves past the end; a closing card that
    starts inside the clip keeps the native exit.
    """
    if payload.get("template_id") != "bihuo-02-v1":
        return payload
    cfg = payload.get("config")
    if not isinstance(cfg, dict):
        return payload
    third = cfg.get("third") or {}
    frames = int(cfg.get("frame_count") or cfg.get("frames") or 0)
    fps = float(cfg.get("fps") or 25)
    exit_times = cfg.get("card_exit")
    if not frames or not isinstance(exit_times, list) or len(exit_times) != 2:
        return payload
    last = (frames - 1) / fps
    record = {
        "version": CAPSULE_ENDING,
        "original_exit": list(exit_times),
        "held": False,
    }
    if float(third.get("title_at", 0)) <= last:
        record["reason"] = "closing card starts inside the clip"
    elif float(exit_times[0]) > last:
        record["reason"] = "card already stays to the end"
    else:
        held = [
            round(float(cfg["duration"]) + 1.0, 3),
            round(float(cfg["duration"]) + 1.35, 3),
        ]
        cfg["card_exit"] = held
        spec = cfg.get("_list_spec")
        if isinstance(spec, dict) and isinstance(spec.get("events"), dict):
            spec["events"]["exit"] = list(held)
        record.update(
            held=True, exit=held, reason="closing card starts after the last frame"
        )
    cfg["capsule_ending"] = record
    return payload


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
    merged = []
    for cue in cfg["captions"]:
        lines = cue.get("lines", [{"text": cue["text"], "emphasis_spans": []}])
        if len(lines) == 2:
            short = min(len(re.findall(r"\w", line["text"])) for line in lines)
            whole = _merged_line(lines)
            if short <= ORPHAN_CHARS and width(whole) <= limit:
                changed.append({**cue, "lines": [whole]})
                merged.append(cue["text"])
                continue
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
    if merged:
        payload["config"]["caption_lines"] = {
            "version": CAPTION_LINES,
            "merged": merged,
        }
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


_FUNCTION_WORDS = set(
    "的了着过吗呢吧啊呀嘛就才都也还又而但并再更很太把被让给对在是和跟或我你他她它们这那个一"
)


def _token_offsets(transcript: Transcript) -> tuple[str, list[int]]:
    starts, cursor = [], 0
    for word in transcript.tokens:
        starts.append(cursor)
        cursor += len(word.text)
    return "".join(word.text for word in transcript.tokens), starts


def _span_at(transcript: Transcript, starts: list[int], a: int, b: int) -> dict | None:
    """Token span covering source characters [a, b); None if it is empty."""
    ids = [
        word.id
        for word, start in zip(transcript.tokens, starts, strict=True)
        if start < b and start + len(word.text) > a
    ]
    return {"first_token_id": ids[0], "last_token_id": ids[-1]} if ids else None


def repair_provider_shapes(
    raw: dict[str, Any], transcript: Transcript
) -> dict[str, Any]:
    """Deterministic, free repairs of two recurring provider slips (dev 11-28).

    1. ``opening.title``/``subtitle`` returned as plain text instead of token
       spans: bind verbatim text (punctuation ignored) to its recorded tokens,
       otherwise to the opening clause sharing the most characters with it.
    2. No caption carries any keyword emphasis although the contract needs
       some: mark one lexical word (2–4 characters, not a function word) per
       caption. Speech, clocks and caption spans are untouched; the strict
       contract still checks the result.
    """
    if not isinstance(raw, dict):
        return raw
    text, starts = _token_offsets(transcript)
    index = {word.id: i for i, word in enumerate(transcript.tokens)}
    changed = deepcopy(raw)
    notes = []
    opening = changed.get("opening")
    if isinstance(opening, dict) and any(
        isinstance(opening.get(k), str) for k in ("title", "subtitle")
    ):
        intro_id = opening.get("intro_last_token_id")
        intro = (
            index.get(intro_id, len(starts) - 1)
            if isinstance(intro_id, str)
            else len(starts) - 1
        )
        limit = starts[intro] + len(transcript.tokens[intro].text)
        head = text[:limit]
        clean = re.compile(r"[\W_]+")
        clauses = [m.span() for m in re.finditer(r"[^，。！？；,.!?;、\s]+", head)]
        for key in ("title", "subtitle"):
            value = opening.get(key)
            if not isinstance(value, str):
                continue
            wanted = clean.sub("", value)
            bound = None
            if wanted:
                plain = [(i, ch) for i, ch in enumerate(head) if not clean.match(ch)]
                joined = "".join(ch for _, ch in plain)
                at = joined.find(wanted)
                if at >= 0:
                    a, b = plain[at][0], plain[at + len(wanted) - 1][0] + 1
                    bound = _span_at(transcript, starts, a, b)
            if bound is None and clauses and wanted:
                a, b = max(
                    clauses, key=lambda c: len(set(head[c[0] : c[1]]) & set(wanted))
                )
                bound = _span_at(transcript, starts, a, b)
            if bound is None:
                return raw
            opening[key] = bound
        notes.append("开场标题按原话对齐到口播词。")
    captions = changed.get("captions")
    if (
        isinstance(captions, list)
        and captions
        and all(isinstance(c, dict) and not c.get("emphasis") for c in captions)
        and len(re.findall(r"\w", text)) >= 12
    ):
        safe, _ = text_boundaries(text)
        cuts = sorted(safe | {0, len(text)})
        for cue in captions:
            if (
                cue.get("first_token_id") not in index
                or cue.get("last_token_id") not in index
            ):
                return raw
            first, last = index[cue["first_token_id"]], index[cue["last_token_id"]]
            a = starts[first]
            b = starts[last] + len(transcript.tokens[last].text)
            brk = index.get(cue.get("line_break_after_token_id") or "")
            split = (
                starts[brk] + len(transcript.tokens[brk].text)
                if brk is not None
                else None
            )
            edges = [x for x in cuts if a <= x <= b]
            words = []
            for x, y in zip(edges, edges[1:], strict=False):
                word = text[x:y]
                core = re.sub(r"\W+$", "", word)
                if not 2 <= len(core) <= 4 or not re.fullmatch(r"\w+", core):
                    continue
                if core[0] in _FUNCTION_WORDS or core[-1] in _FUNCTION_WORDS:
                    continue
                if split is not None and x < split < x + len(core):
                    continue
                words.append((len(core), x, x + len(core)))
            if words:
                _, x, y = max(words, key=lambda w: (w[0], w[1]))
                span = _span_at(transcript, starts, x, y)
                if span:
                    cue["emphasis"] = [span]
        if any(c.get("emphasis") for c in captions):
            notes.append("字幕重点词按原话补齐。")
    if not notes:
        return raw
    warnings = changed.setdefault("warnings", [])
    notice = "".join(notes)
    if isinstance(warnings, list):
        if len(warnings) < 12:
            warnings.append(notice)
        else:
            warnings[-1] = str(warnings[-1])[: 299 - len(notice)] + "；" + notice
    return changed


def verify_plan(
    raw: dict[str, Any],
    transcript: Transcript,
    cards: list[dict[str, Any]],
    *,
    require_semantic_captions: bool = False,
    allow_mixed_body: bool = True,
) -> dict[str, Any]:
    raw = fit_recorded_display_spans(
        repair_provider_shapes(raw, transcript), transcript
    )
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
    template_id: str | None = None,
    sync_policy: str = sync.OFF,
    frame_policy: str = framing.OFF,
) -> dict[str, Any]:
    if recipe_compiler is None:
        raise ValueError("Bihuo compilation requires its selected recipe compiler")

    def fitted_recipe(resolved: dict, **options: Any) -> dict:
        from .conditional_layout import prepare

        # Speech-led visual timing is a versioned compile-time policy; the
        # saved plan, word clock and installed bundle stay unchanged.
        timed, record = sync.apply(resolved, template_id, sync_policy)
        payload = prepare(
            _fit_capsule_captions(
                recipe_compiler(
                    native_caption_text(timed, verified, transcript), **options
                ),
                transcript,
            )
        )
        payload = _hold_capsule_card(payload)
        # Opening info card in spoken order (bihuo-info-card/1).
        payload = info_card.apply(payload)
        if (
            sync_policy != sync.OFF
            and isinstance(payload, dict)
            and isinstance(payload.get("config"), dict)
        ):
            payload["config"]["sync_policy"] = record
        if frame_policy not in framing.POLICIES:
            raise ValueError("Unknown frame layout policy")
        if (
            frame_policy != framing.OFF
            and isinstance(payload, dict)
            and isinstance(payload.get("config"), dict)
        ):
            # Render-time face safety and transitions (bihuo-frame/1).
            payload["config"]["frame_policy"] = {"version": frame_policy}
        return payload

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
