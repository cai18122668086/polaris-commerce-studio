"""Compile allowed native field anchors from measured token occurrences only."""

from typing import Any

from .video_editing_contracts import SemanticBeat, Transcript, TranscriptToken


def emphasis_text(text: str, policy: str) -> str:
    if policy == "preserve":
        return text.strip()
    if policy != "omit_sentence_punctuation":
        raise ValueError("Unknown native punctuation policy")
    # Retain decimal/thousands/ratio punctuation and unit symbols (%, /, ±...).
    output = []
    for i, char in enumerate(text):
        internal_number = (
            0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
            and char in ".,:"
        )
        if char not in "，。！？、；：,.!?;:" or internal_number:
            output.append(char)
    return "".join(output).strip()


def word_bindings(
    beat: SemanticBeat,
    transcript: Transcript,
    contract: dict[str, Any],
    allowed_assets: set[str],
) -> dict[str, Any]:
    if contract["group_id"] != beat.group_id:
        raise ValueError("Wrong original native input contract")
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    if beat.first_token_id not in positions or beat.last_token_id not in positions:
        raise ValueError("Unknown source occurrence")
    first, last = positions[beat.first_token_id], positions[beat.last_token_id]
    if first > last:
        raise ValueError("Native meaning span is reversed")
    start_ms, end_ms = transcript.tokens[first].start_ms, transcript.tokens[last].end_ms
    fps = contract["native_fps"]
    if type(fps) not in {int, float} or fps <= 0:
        raise ValueError("Native frame rate is not declared")
    used = set()

    def field(path: str, allowed: set[str]) -> None:
        if path not in allowed or path in used:
            raise ValueError("Native path is not allowed or was assigned twice")
        used.add(path)

    def span(begin: str, finish: str) -> list[TranscriptToken]:
        if begin not in positions or finish not in positions:
            raise ValueError("Unknown measured word anchor")
        a, b = positions[begin], positions[finish]
        if not first <= a <= b <= last:
            raise ValueError("Native text/event anchor leaves its meaning span")
        return transcript.tokens[a : b + 1]

    texts = []
    for anchor in beat.native_text:
        field(anchor.path, set(contract["text_paths"]))
        tokens = span(anchor.first_token_id, anchor.last_token_id)
        text = emphasis_text("".join(t.text for t in tokens), anchor.punctuation)
        if not text:
            raise ValueError("Native text anchor has no visible content")
        texts.append(
            {
                "path": anchor.path,
                "text": text,
                "token_ids": [t.id for t in tokens],
                "punctuation_policy": anchor.punctuation,
            }
        )
    event_units = {row["path"]: row["unit"] for row in contract["event_paths"]}
    events = []
    for event_anchor in beat.native_events:
        field(event_anchor.path, set(event_units))
        token = span(event_anchor.token_id, event_anchor.token_id)[0]
        measured = token.start_ms if event_anchor.edge == "start" else token.end_ms
        relative = measured - start_ms
        if not 0 <= relative <= end_ms - start_ms:
            raise ValueError("Measured event exceeds current native interval")
        unit = event_units[event_anchor.path]
        if unit == "frames":
            value: int | float = round(relative * fps / 1000)
            quantization = value * 1000 / fps - relative
        elif unit == "seconds":
            value, quantization = relative / 1000, 0.0
        else:
            raise ValueError("Unknown original native time unit")
        events.append(
            {
                "path": event_anchor.path,
                "value": value,
                "unit": unit,
                "token_id": token.id,
                "edge": event_anchor.edge,
                "measured_anchor_ms": measured,
                "frame_quantization_ms": round(quantization, 6),
            }
        )
    media = []
    for media_anchor in beat.native_media:
        field(media_anchor.path, {r["path"] for r in contract["resource_paths"]})
        if (
            media_anchor.asset_id not in allowed_assets
            or media_anchor.asset_id not in beat.asset_ids
        ):
            raise ValueError("Native media is not an available selected project asset")
        media.append({"path": media_anchor.path, "asset_id": media_anchor.asset_id})
    branches = {
        field["native_branch"]
        for field in contract.get("fields", [])
        if field["path"] in used and "native_branch" in field
    }
    if len(branches) > 1:
        raise ValueError("Native anchors cannot mix fields from separate branches")
    return {
        "version": "tengli.native-word-bindings/1",
        "beat_id": beat.id,
        "group_id": beat.group_id,
        "clock": {"start_ms": start_ms, "end_ms": end_ms, "native_fps": fps},
        "text": texts,
        "events": events,
        "media": media,
        "native_schema_validation": "not_performed",
        "runtime_validation": "unverified",
    }
