"""A source-owned tutorial clock, shared by every visual template.

Material intent is resolved before layout. A template cannot discard a chosen
recording or shorten its source playback to fit a decorative scene interval.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .motion_library import atomic_json, read_json, sha256
from .video_editing_contracts import Transcript

VERSION = "tengli.tutorial-content/1"
READ_HOLD_MS = 500


class TutorialStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    first_token_id: str
    last_token_id: str


class TutorialIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[TutorialStep] = Field(min_length=1, max_length=40)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def selected_recordings(cards: list[dict]) -> list[dict]:
    return sorted(
        [dict(card) for card in cards if card.get("kind") == "video"],
        key=lambda row: row["id"],
    )


def content_context(
    source_id: str, transcript: Transcript, cards: list[dict]
) -> dict | None:
    recordings = selected_recordings(cards)
    if not recordings:
        return None
    for card in recordings:
        if not isinstance(card.get("duration_ms"), int) or card["duration_ms"] <= 0:
            raise ValueError("Tutorial recordings require measured durations")
    context = {
        "version": VERSION,
        "source_id": source_id,
        "source_sha256": transcript.source_sha256,
        "transcript_sha256": digest(transcript.model_dump(mode="json")),
        "recordings": recordings,
    }
    return {**context, "key": digest(context)}


def cache_root(tasks: Path, context: dict) -> Path:
    key = context["key"]
    if (
        not isinstance(key, str)
        or len(key) != 64
        or any(c not in "0123456789abcdef" for c in key)
    ):
        raise ValueError("Invalid tutorial content key")
    root = (tasks / "_tutorial" / key).resolve()
    if os.name == "nt" and not str(root).startswith("\\\\?\\"):
        root = Path("\\\\?\\" + str(root))
    return root


def validate_intent(value: dict, transcript: Transcript, context: dict) -> dict:
    plan = TutorialIntent.model_validate(value)
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    selected = {row["id"]: row for row in context["recordings"]}
    seen: set[str] = set()
    previous = -1
    for step in plan.steps:
        if step.asset_id not in selected or step.asset_id in seen:
            raise ValueError("Tutorial must use each selected recording exactly once")
        if step.first_token_id not in positions or step.last_token_id not in positions:
            raise ValueError("Tutorial references an unknown recorded word")
        first, last = positions[step.first_token_id], positions[step.last_token_id]
        if not previous < first <= last:
            raise ValueError("Tutorial speech spans must be ordered and disjoint")
        previous = last
        seen.add(step.asset_id)
    if seen != set(selected):
        raise ValueError(
            "Tutorial is missing selected recordings; layout cannot silently omit them"
        )
    return plan.model_dump(mode="json")


def legacy_suite_intent(
    raw: dict, transcript: Transcript, context: dict
) -> dict | None:
    """Reuse complete old model bindings, with context through the next step.

    The old show_at anchor can be at a phrase's last word. Tutorial playback
    instead starts at its actual instruction and retains the following result
    explanation, until the next instruction or the spoken conclusion.
    """
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    selected = {row["id"] for row in context["recordings"]}
    rows = [row for row in raw.get("materials", []) if row.get("asset_id") in selected]
    if len(rows) != len(selected) or {row["asset_id"] for row in rows} != selected:
        return None
    rows.sort(key=lambda row: positions[row["first_token_id"]])
    closing = ((raw.get("conclusion") or {}).get("first") or {}).get("first_token_id")
    end = positions[closing] - 1 if closing in positions else len(transcript.tokens) - 1
    steps = []
    for index, row in enumerate(rows):
        last = (
            positions[rows[index + 1]["first_token_id"]] - 1
            if index + 1 < len(rows)
            else end
        )
        steps.append(
            {
                "asset_id": row["asset_id"],
                "first_token_id": row["first_token_id"],
                "last_token_id": transcript.tokens[last].id,
            }
        )
    return validate_intent({"steps": steps}, transcript, context)


def save_plan(
    tasks: Path, context: dict, intent: dict, transcript: Transcript, origin: dict
) -> dict:
    intent = validate_intent(intent, transcript, context)
    root = cache_root(tasks, context)
    document = {
        "version": VERSION,
        "context": context,
        "intent": intent,
        "origin": origin,
    }
    plan_sha = digest(document)
    path = root / (plan_sha + ".json")
    if not path.exists():
        atomic_json(path, document)
    # The first accepted content plan owns the shared source/asset clock.
    # Concurrent template requests may add evidence, never replace that clock.
    index = root / "selected.json"
    pointer = root / ("pick-" + uuid4().hex[:8] + ".json")
    atomic_json(pointer, {"plan_sha256": plan_sha, "file_sha256": sha256(path)})
    with suppress(FileExistsError):
        os.link(pointer, index)
    return load_plan(tasks, context, transcript)


def load_plan(tasks: Path, context: dict, transcript: Transcript) -> dict:
    root = cache_root(tasks, context)
    pointer = read_json(root / "selected.json")
    name = pointer["plan_sha256"]
    if (
        not isinstance(name, str)
        or len(name) != 64
        or any(c not in "0123456789abcdef" for c in name)
    ):
        raise ValueError("Invalid shared tutorial plan reference")
    path = root / (name + ".json")
    document = read_json(path)
    if (
        sha256(path) != pointer["file_sha256"]
        or digest(document) != name
        or document["context"] != context
    ):
        raise ValueError("Shared tutorial input or plan changed")
    validate_intent(document["intent"], transcript, context)
    return {**document, "sha256": name, "file_sha256": pointer["file_sha256"]}


def optional_plan(tasks: Path, context: dict, transcript: Transcript) -> dict | None:
    if not (cache_root(tasks, context) / "selected.json").exists():
        return None
    return load_plan(tasks, context, transcript)


def accept_output(
    raw: dict, context: dict | None, transcript: Transcript, tasks: Path, origin: dict
) -> tuple[dict, dict | None]:
    native = dict(raw)
    submitted = native.pop("tutorial_steps", None)
    if context is None:
        if submitted is not None:
            raise ValueError("Tutorial steps require selected recordings")
        return native, None
    shared = optional_plan(tasks, context, transcript)
    if shared is None:
        intent = (
            {"steps": submitted}
            if submitted is not None
            else legacy_suite_intent(native, transcript, context)
        )
        if intent is None:
            raise ValueError("Missing shared tutorial_steps for selected recordings")
        shared = save_plan(tasks, context, intent, transcript, origin)
    return native, shared


def planning_hint(context: dict, shared: dict | None = None) -> dict:
    return {
        "version": VERSION,
        "key": context["key"],
        "required_recordings": context["recordings"],
        "shared_steps": shared["intent"]["steps"] if shared else None,
        "policy": (
            "教程素材和台词对应关系独立于模板。返回顶层tutorial_steps数组，每项仅含"
            "asset_id、first_token_id、last_token_id；每段选中录屏恰好出现一次，"
            "按真实操作顺序绑定完整台词区间，包括该步骤的操作与结果说明，区间互不重叠。"
            "shared_steps已给出时直接复用，不得因模板换位、图卡数量或动效时长删减录屏。"
            "录屏从头完整播放，具体秒数由程序测量；口播更快时程序在步骤交接处留出演示时间，"
            "不截短、不加速、不以静态截图冒充录屏。原生materials/native_media只负责模板装饰，"
            "不能代替tutorial_steps的完整教程素材计划。"
        ),
    }


def augment_request(
    body: dict, context: dict | None, shared: dict | None = None
) -> dict:
    if context is None:
        return body
    hint = planning_hint(context, shared)
    messages = [dict(row) for row in body["messages"]]
    payload = json.loads(messages[1]["content"])
    payload["tutorial_material_plan"] = hint
    messages[0]["content"] += "\n教程录屏共用规则/1：" + hint["policy"]
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False)
    return {**body, "messages": messages}


def verify_capture(
    folder: Path,
    context: dict,
    transcript: Transcript,
    settings: Any,
    result: dict,
    receipt: dict,
) -> None:
    shared = load_plan(settings.video_editing_tasks_dir, context, transcript)
    if (
        read_json(folder / "tutorial-plan.json") != shared
        or receipt.get("tutorial_plan_sha256") != shared["sha256"]
        or result.get("tutorial_plan_sha256") != shared["sha256"]
    ):
        raise ValueError("Captured tutorial plan no longer matches the shared content")


def task_context(
    session: Any, settings: Any, source_id: str, ids: list[str], transcript: Transcript
) -> tuple[dict, dict]:
    """Resolve recordings against the source owner/project, never client paths."""
    from .video_editing_materials import PREFIX, material_cards, project_material_files
    from .video_editing_task_models import EditingSourceRecord

    source = session.get(EditingSourceRecord, source_id)
    if source is None or source.media_sha256 != transcript.source_sha256:
        raise ValueError("Tutorial source no longer matches the recorded transcript")
    assets = project_material_files(
        session,
        settings,
        source,
        {PREFIX + str(value) for value in ids},
        verify_bytes=True,
    )
    cards = material_cards(assets, include_video_durations=True)
    if any(card["kind"] != "video" for card in cards):
        raise ValueError("Tutorial playback selection must contain recordings")
    context = content_context(source.id, transcript, cards)
    if context is None:
        raise ValueError("Tutorial playback has no selected recordings")
    return load_plan(settings.video_editing_tasks_dir, context, transcript), assets


def source_to_output(clock: dict, source_ms: int, *, end: bool = False) -> int:
    return source_ms + sum(
        hold["duration_ms"]
        for hold in clock["holds"]
        if hold["source_ms"] < source_ms or (not end and hold["source_ms"] == source_ms)
    )


def schedule(shared: dict, transcript: Transcript) -> dict:
    context, intent = shared["context"], shared["intent"]
    validate_intent(intent, transcript, context)
    tokens = {token.id: token for token in transcript.tokens}
    cards = {row["id"]: row for row in context["recordings"]}
    holds: list[dict] = []
    steps = []
    delay = 0
    for index, step in enumerate(intent["steps"]):
        first, last = tokens[step["first_token_id"]], tokens[step["last_token_id"]]
        start = first.start_ms + delay
        duration = cards[step["asset_id"]]["duration_ms"]
        playback_end = start + duration
        boundary = (
            tokens[intent["steps"][index + 1]["first_token_id"]].start_ms
            if index + 1 < len(intent["steps"])
            else last.end_ms
        )
        pause = max(0, playback_end + READ_HOLD_MS - (boundary + delay))
        if pause:
            holds.append(
                {
                    "source_ms": boundary,
                    "output_start_ms": boundary + delay,
                    "duration_ms": pause,
                }
            )
            delay += pause
        end = boundary + delay
        steps.append(
            {
                **step,
                "index": index + 1,
                "label": cards[step["asset_id"]].get("viewed_identity")
                or cards[step["asset_id"]].get("semantic_use")
                or f"步骤 {index + 1}",
                "asset_sha256": cards[step["asset_id"]]["sha256"],
                "start_ms": start,
                "playback_end_ms": playback_end,
                "end_ms": end,
                "source_in_ms": 0,
                "source_out_ms": duration,
                "playback_rate": 1,
                "tail_hold_ms": end - playback_end,
            }
        )
    clock = {
        "version": VERSION,
        "content_sha256": shared["sha256"],
        "source_duration_ms": transcript.duration_ms,
        "duration_ms": transcript.duration_ms + delay,
        "holds": holds,
        "steps": steps,
    }
    if any(
        row["end_ms"] < row["playback_end_ms"] or row["tail_hold_ms"] < READ_HOLD_MS
        for row in steps
    ):
        raise ValueError("Tutorial material cannot be cut short by a scene transition")
    return {**clock, "sha256": digest(clock)}


def timestamp_expression(clock: dict) -> str:
    return "PTS-STARTPTS" + "".join(
        f"+{hold['duration_ms'] / 1000:.6f}/TB*gte((PTS-STARTPTS)*TB+0.000001,"
        f"{hold['source_ms'] / 1000:.6f})"
        for hold in clock["holds"]
    )
