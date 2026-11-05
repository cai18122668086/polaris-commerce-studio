"""Append-only stage attempts; legacy jobs have no invented historical times."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def transition(
    history: list[dict[str, Any]] | None,
    stage: str,
    *,
    finish: bool = False,
    outcome: str | None = None,
) -> list[dict[str, Any]]:
    history = [dict(item) for item in (history or [])]
    now = datetime.now(UTC)
    stamp = now.isoformat()
    if history and history[-1].get("finished_at") is None:
        if history[-1]["stage"] == stage and not finish:
            return history
        last = history[-1]
        last["finished_at"] = stamp
        last["duration_seconds"] = max(
            0,
            round(
                (now - datetime.fromisoformat(last["started_at"])).total_seconds(), 3
            ),
        )
        last["outcome"] = outcome or "advanced"
    if not finish:
        history.append(
            {
                "stage": stage,
                "started_at": stamp,
                "finished_at": None,
                "duration_seconds": None,
            }
        )
    return history
