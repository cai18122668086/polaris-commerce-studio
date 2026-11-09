"""Apply explicit per-render decisions against a frozen native candidate."""

from typing import Any

from .video_editing_contracts import NativeRenderEdits, SemanticBeat

SOURCE_GROUP = "Z-M00"
MUSIC_REDUCTION_DB = 6


def available_render_edits(
    semantic: dict, recipes: dict, choices: dict | None
) -> tuple[set[str], bool]:
    avoid_original = any(
        row["target_kind"] == "group"
        and row["target_id"] == SOURCE_GROUP
        and row["choice"] == "avoid"
        for row in (choices or {}).get("notes", [])
    )
    editable = {
        beat["id"]
        for beat in semantic["beats"]
        if beat["group_id"] != SOURCE_GROUP and beat["id"] in recipes["entries"]
    }
    return (set() if avoid_original else editable), bool(
        (recipes.get("sound") or {}).get("music")
    )


def validate_render_edits(
    edits: NativeRenderEdits, semantic: dict, recipes: dict, choices: dict | None
) -> None:
    editable, has_music = available_render_edits(semantic, recipes, choices)
    if not set(edits.source_only_beat_ids).issubset(editable) or (
        edits.music is not None and not has_music
    ):
        raise ValueError("Native edits must address this candidate's editable inputs")


def source_only(beat: SemanticBeat) -> SemanticBeat:
    return beat.model_copy(
        update={
            "group_id": SOURCE_GROUP,
            "asset_ids": [],
            "native_text": [],
            "native_events": [],
            "native_media": [],
            "relation_items": [],
            "reason": "用户指定本次成片该段保留本期原景和主字幕。",
            "locked_by_user": True,
        }
    )


def edited_segment_receipt(beat: SemanticBeat, start: int, end: int) -> dict[str, Any]:
    return {
        "beat_id": beat.id,
        "original_group_id": beat.group_id,
        "applied_group_id": SOURCE_GROUP,
        "first_token_id": beat.first_token_id,
        "last_token_id": beat.last_token_id,
        "start_ms": start,
        "end_ms": end,
        "locked_by_user": True,
    }
