"""Bind the original Z-M11 typewriter to measured characters."""

from itertools import pairwise

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_word_bindings import emphasis_text

PAPER_GROUP = "Z-M11"
PAPER_TEMPLATE_ID = "unified-paper-typewriter-v1"
_FPS = 30


def paper_character_times(
    beat: SemanticBeat, native: dict, transcript: Transcript
) -> list[list[float]]:
    """All glyphs from one measured token appear on that token's own start."""
    tokens = {token.id: token for token in transcript.tokens}
    positions = {token_id: i for i, token_id in enumerate(tokens)}
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    start, end = (native["clock"][key] for key in ("start_ms", "end_ms"))
    duration = round((end - start) * _FPS / 1000) / _FPS
    if beat.relation != "parallel" or len(beat.relation_items) != 2:
        raise ValueError("The paper requires two independently spoken rows")
    result = []
    for i, item in enumerate(beat.relation_items):
        label_path, body_path = (
            f"/content/rows/{i}/{key}" for key in ("label", "text")
        )
        label, body = text[label_path], text[body_path]
        event = events[f"/timing/events/row{i}"]
        pieces = [
            (emphasis_text(tokens[key].text, body["punctuation_policy"]), tokens[key])
            for key in body["token_ids"]
        ]
        values = [
            (token.start_ms - start) / 1000 for glyphs, token in pieces for _ in glyphs
        ]
        if (
            set(item.native_text_paths) != {label_path, body_path}
            or item.native_media_paths
            or item.asset_ids
            or not positions[item.first_token_id]
            <= positions[label["token_ids"][0]]
            <= positions[label["token_ids"][-1]]
            < positions[body["token_ids"][0]]
            <= positions[body["token_ids"][-1]]
            <= positions[item.last_token_id]
            or event["edge"] != "start"
            or event["token_id"] != label["token_ids"][0]
            or not 1 <= len(label["text"]) <= 3
            or not 1 <= len(body["text"]) <= 12
            or any(char.isspace() for char in label["text"] + body["text"])
            or "".join(glyphs for glyphs, _ in pieces) != body["text"]
            or not event["value"] <= values[0] <= values[-1] <= duration - 0.35
        ):
            raise ValueError(
                "Paper labels and glyphs need their own measured word range"
            )
        result.append(values)
    if (
        positions[beat.relation_items[0].last_token_id]
        >= positions[beat.relation_items[1].first_token_id]
        or result[0][-1] + 0.20 > events["/timing/events/row1"]["value"]
        or any(a > b for row in result for a, b in pairwise(row))
    ):
        raise ValueError("The original paper needs two ordered, readable rows")
    return result
