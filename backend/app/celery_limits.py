"""Per-queue Celery time limits derived from Settings."""

from __future__ import annotations

from typing import Any

from .config import Settings

# Queue name -> Settings limit family.
QUEUE_LIMITS = {
    "default": "image",
    "domestic_detail_v431": "detail",
    "one_click_replica": "replica",
    "editing": "editing",
    "editing-planning": "planning",
}
TASK_LIMITS = {
    "polaris.process_job": "image",
    "polaris.cancel_job": "cancel",
    "polaris.process_editing_task": "editing",
    "polaris.process_editing_planning_task": "planning",
}


def limits(settings: Settings, family: str) -> dict[str, int]:
    soft = int(getattr(settings, f"celery_soft_time_limit_{family}_seconds"))
    return {
        "soft_time_limit": soft,
        "time_limit": soft + settings.celery_time_limit_grace_seconds,
    }


def queue_limits(settings: Settings, queue: str | None) -> dict[str, int]:
    return limits(settings, QUEUE_LIMITS.get(queue or "default", "image"))


def task_annotations(settings: Settings) -> dict[str, dict[str, Any]]:
    return {name: limits(settings, family) for name, family in TASK_LIMITS.items()}
