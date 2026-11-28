"""A dead worker's unacked job delivery is returned to the queue; live ones never."""

import json

from app.outbox import orphaned_job_tags


def _raw(task: str, task_id: str) -> str:
    message = {"headers": {"task": task, "id": task_id}, "body": ""}
    return json.dumps([message, "", "default"])


def test_only_job_deliveries_without_a_live_worker_are_restored():
    entries = {
        "tag-dead": _raw("polaris.process_job", "task-dead"),
        "tag-live": _raw("polaris.process_job", "task-live"),
        "tag-editing": _raw("polaris.process_editing_task", "task-editing"),
        "tag-gone": None,
        "tag-garbage": "not json",
    }
    assert orphaned_job_tags(entries, {"task-live"}) == ["tag-dead"]


def test_nothing_is_restored_when_every_delivery_is_held():
    entries = {"tag": _raw("polaris.process_job", "task")}
    assert orphaned_job_tags(entries, {"task"}) == []
