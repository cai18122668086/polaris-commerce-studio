"""Conservative reference spelling/punctuation recovery before semantic planning.

Only equal-length, nearly identical measured Mandarin units with identical
phonetic readings can adopt reference spelling. No words or times are invented.
The unmodified ASR transcript and the automatic decision are saved separately.
"""

import hashlib
import importlib.metadata
import re
import unicodedata
from typing import Any

from .video_editing_contracts import Transcript, TranscriptUtterance

VERSION = "phonetic-reference/1"
PINNED_PINYIN = "0.55.0"
UNIT = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
CLAUSE_END = re.compile(r"[，,。！？!?；;：:\n]")
SENTENCE_END = re.compile(r"[。！？!?；;\n]")


def reference_profile() -> dict[str, str]:
    version = importlib.metadata.version("pypinyin")
    if version != PINNED_PINYIN:
        raise ValueError("Reference phonetic dictionary version changed")
    return {"processing": VERSION, "pypinyin": version}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def reconcile_reference(
    transcript: Transcript, reference: str | None, parent_sha256: str
) -> tuple[Transcript, dict[str, Any]]:
    receipt: dict[str, Any] = {
        "version": VERSION,
        "status": "skipped",
        "parent_transcript_sha256": parent_sha256,
        "source_sha256": transcript.source_sha256,
        "audio_sha256": transcript.audio_sha256,
        "clock_changed": False,
        "automatic": True,
    }

    def skipped(reason: str) -> tuple[Transcript, dict[str, Any]]:
        return transcript, {**receipt, "reason": reason}

    if not reference or transcript.language != "zh" or not transcript.tokens:
        return skipped("no Mandarin reference")
    if transcript.text_status != "automatic" or transcript.reference_reconciliation:
        return skipped("preserve an already corrected or reconciled transcript")
    reference = reference.strip()
    matches = list(UNIT.finditer(reference))
    measured = [list(UNIT.finditer(t.text)) for t in transcript.tokens]
    if len(matches) != len(measured) or any(len(m) != 1 for m in measured):
        return skipped("reference adds, removes, or splits measured units")
    # Gaps can contain punctuation and whitespace, never unrecognized content.
    gaps = [reference[: matches[0].start()]] if matches else []
    gaps += [
        reference[m.end() : matches[i + 1].start() if i + 1 < len(matches) else None]
        for i, m in enumerate(matches)
    ]
    if any(
        not (c.isspace() or unicodedata.category(c).startswith("P"))
        for gap in gaps
        for c in gap
    ):
        return skipped("reference contains units without measured speech")
    before = [m[0].group() for m in measured]
    after = [m.group() for m in matches]
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    if len(changed) > min(4, max(1, len(before) // 20)):
        return skipped("reference differs beyond conservative spelling capacity")
    if any(
        b == a + 2 and b - 1 in changed
        for a, b in zip(changed, changed[2:], strict=False)
    ):
        return skipped("reference replaces more than two consecutive speech units")
    if changed:
        from pypinyin import Style, lazy_pinyin

        receipt["dictionary"] = reference_profile()
        for i in changed:
            a, b = before[i], after[i]
            if not re.fullmatch(r"[\u3400-\u9fff]", a) or not re.fullmatch(
                r"[\u3400-\u9fff]", b
            ):
                return skipped("numbers and names cannot be automatically replaced")
            if lazy_pinyin(a, style=Style.NORMAL) != lazy_pinyin(b, style=Style.NORMAL):
                return skipped("reference changes spoken phonetic units")
    data = transcript.model_dump(mode="json")
    prefix = _sha(parent_sha256 + reference + VERSION)[:12]
    changes = []
    for i, token in enumerate(data["tokens"]):
        old = token["text"]
        # One reference unit remains one original measured interval.
        token["text"] = (gaps[0] if i == 0 else "") + after[i] + gaps[i + 1]
        token["id"] = f"r{prefix}-{token['id']}"
        if old != token["text"]:
            changes.append(
                {
                    "token_id": token["id"],
                    "before": old,
                    "after": token["text"],
                    "kind": "homophone" if i in changed else "punctuation",
                }
            )
    # Use supplied punctuation as clause boundaries while retaining real clocks.
    utterances: list[dict[str, Any]] = []
    first = 0
    for i, token in enumerate(data["tokens"]):
        if CLAUSE_END.search(token["text"]) or i == len(data["tokens"]) - 1:
            selected = data["tokens"][first : i + 1]
            utterances.append(
                TranscriptUtterance(
                    id=f"r{prefix}-u{len(utterances):05d}",
                    text="".join(t["text"] for t in selected),
                    token_ids=[t["id"] for t in selected],
                    start_ms=selected[0]["start_ms"],
                    end_ms=selected[-1]["end_ms"],
                ).model_dump(mode="json")
            )
            first = i + 1
    receipt.update(
        status="applied",
        reference_sha256=_sha(reference),
        before_text_sha256=_sha("".join(t.text for t in transcript.tokens)),
        homophone_changes=len(changed),
        changes=changes,
        unit_count=len(before),
        timing_review="unreviewed",
        text_review="automatic reference comparison, not user correction",
    )
    data.update(
        tokens=data["tokens"],
        utterances=utterances,
        parent_transcript_sha256=parent_sha256,
        reference_text=reference,
        reference_matches=True,
        differences=[],
        reference_reconciliation=receipt,
        processing_version=transcript.processing_version + "+" + VERSION,
        warnings=[
            *transcript.warnings,
            "已自动按近乎一致的参考稿核对同音字与标点；原始识别另存，实录词点不变，仍可校对。",
        ],
    )
    return Transcript.model_validate(data), receipt


def caption_boundaries(transcript: Transcript) -> dict[str, Any]:
    """Reliable reference stops constrain cue grouping; long clauses stay flexible."""
    if transcript.reference_reconciliation.get("status") != "applied":
        return {}
    ends = []
    sentence_ends = []
    long_clause_ids: list[str] = []
    current = []
    for i, token in enumerate(transcript.tokens):
        current.append(token)
        if CLAUSE_END.search(token.text) or i == len(transcript.tokens) - 1:
            ends.append(token.id)
            if sum(len(re.findall(r"\w", t.text)) for t in current) > 36:
                long_clause_ids.extend(t.id for t in current[:-1])
            current = []
        if SENTENCE_END.search(token.text):
            sentence_ends.append(token.id)
    return {
        "policy": "verified-reference-clauses/1",
        "cue_end_token_ids": ends,
        "sentence_end_token_ids": sentence_ends,
        "long_clause_token_ids": long_clause_ids,
    }
