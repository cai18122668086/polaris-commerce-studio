"""Build the ``supplement_mg`` render input from the actual transcript.

Called by the editing worker right before the suite render, only when the
planning snapshot froze ``supplement.mg`` and ``video_supplement_mg_enabled``
is on. One model call per transcript (cached); deterministic fallback.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..video_editing_supplement_plan import plan_mg
from .catalog import CATALOG_VERSION, STYLES, prompt_catalog, validate_params


def utterance_rows(transcript: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "text": row.text,
            "start_ms": row.start_ms,
            "end_ms": row.end_ms,
        }
        for row in transcript.utterances
        if row.text.strip()
    ]


def supplement_mg_payload(
    settings: Settings,
    frozen_mg: dict[str, Any],
    transcript: Any,
    *,
    ask: Any = None,
    use_model: bool = True,
) -> dict[str, Any] | None:
    if not settings.video_supplement_mg_enabled:
        return None
    style = frozen_mg.get("style") if frozen_mg.get("style") in STYLES else "paper"
    rows = utterance_rows(transcript)
    plan = plan_mg(
        settings,
        rows,
        prompt_catalog(),
        validate_params,
        ask=ask,
        use_model=use_model,
    )
    timing = {row["id"]: row for row in rows}
    cues = []
    for cue in plan["cues"]:
        ids = cue["utterance_ids"]
        cues.append(
            {
                "component": cue["component"],
                "params": cue["params"],
                "utterance_ids": ids,
                "start_ms": timing[ids[0]]["start_ms"],
                "end_ms": timing[ids[-1]]["end_ms"],
            }
        )
    return {
        "catalog": CATALOG_VERSION,
        "style": style,
        "plan_digest": plan["digest"],
        "source": plan["source"],
        "warnings": plan["warnings"],
        "cues": cues,
        "ffmpeg": settings.video_editing_ffmpeg,
        "ffprobe": settings.video_editing_ffprobe,
    }
