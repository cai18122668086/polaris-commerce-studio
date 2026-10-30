"""Consume bounded Chat Completions SSE without accepting incomplete output."""

from __future__ import annotations

import json
import time
from http.client import HTTPException
from typing import Any

MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_EVENT_BYTES = 2 * 1024 * 1024


class PlannerStreamError(RuntimeError):
    def __init__(self, code: str, envelope: dict[str, Any]) -> None:
        super().__init__("The planner stream did not finish with a complete response.")
        self.code = code
        self.envelope = envelope


def read_chat_stream(response: Any, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    content: list[str] = []
    finish: str | None = None
    envelope: dict[str, Any] = {"choices": []}
    total = 0
    chunks = 0
    fields: list[str] = []
    done = False

    def snapshot(complete: bool) -> dict[str, Any]:
        envelope["choices"] = [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": "".join(content)},
            }
        ]
        envelope["_planner_stream"] = {
            "complete": complete,
            "chunks": chunks,
            "bytes": total,
            "finish_reason": finish,
            "usage_received": isinstance(envelope.get("usage"), dict),
        }
        return envelope

    def fail(code: str) -> None:
        raise PlannerStreamError(code, snapshot(False))

    def event() -> None:
        nonlocal chunks, finish, done
        if not fields:
            return
        data = "\n".join(fields)
        fields.clear()
        if data == "[DONE]":
            done = True
            return
        try:
            value = json.loads(data)
        except (ValueError, TypeError):
            fail("PLANNER_STREAM_INVALID")
            return
        if not isinstance(value, dict):
            fail("PLANNER_STREAM_INVALID")
        if value.get("error"):
            fail("PLANNER_STREAM_ERROR")
        chunks += 1
        for key in ("id", "model"):
            observed = value.get(key)
            if observed is not None:
                if not isinstance(observed, str) or (
                    key in envelope and envelope[key] != observed
                ):
                    fail("PLANNER_STREAM_INVALID")
                envelope[key] = observed
        if isinstance(value.get("usage"), dict):
            envelope["usage"] = value["usage"]
        choices = value.get("choices", [])
        if not isinstance(choices, list):
            fail("PLANNER_STREAM_INVALID")
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                fail("PLANNER_STREAM_INVALID")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                fail("PLANNER_STREAM_INVALID")
            text = delta.get("content")
            if text is not None:
                if not isinstance(text, str) or (finish is not None and text):
                    fail("PLANNER_STREAM_INVALID")
                content.append(text)
            reason = choice.get("finish_reason")
            if reason is not None:
                if not isinstance(reason, str) or (
                    finish is not None and reason != finish
                ):
                    fail("PLANNER_STREAM_INVALID")
                finish = reason

    try:
        while not done:
            if time.monotonic() >= deadline:
                fail("PLANNER_STREAM_INTERRUPTED")
            line = response.readline(MAX_EVENT_BYTES + 1)
            if not line:
                if fields:
                    event()
                break
            total += len(line)
            if len(line) > MAX_EVENT_BYTES or total > MAX_STREAM_BYTES:
                fail("PLANNER_STREAM_TOO_LARGE")
            text = line.decode("utf-8-sig").rstrip("\r\n")
            if not text:
                event()
            elif text.startswith("data:"):
                fields.append(text[5:].removeprefix(" "))
                if sum(len(field) for field in fields) > MAX_EVENT_BYTES:
                    fail("PLANNER_STREAM_TOO_LARGE")
    except PlannerStreamError:
        raise
    except (OSError, EOFError, UnicodeError, HTTPException) as exc:
        raise PlannerStreamError("PLANNER_STREAM_INTERRUPTED", snapshot(False)) from exc
    # A syntactically valid prefix is insufficient. Usage may be absent on a
    # relay, but both the terminal choice and the SSE terminator are required.
    if not done or finish is None:
        fail("PLANNER_STREAM_INTERRUPTED")
    return snapshot(True)
