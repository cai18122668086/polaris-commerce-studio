"""Translate our stateless vision calls to the native Responses wire format."""

import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO


class ResponsesStreamError(ValueError):
    """A bounded, redacted stream protocol failure."""


def read_responses_stream(
    response: BinaryIO,
    *,
    deadline: float,
    on_response_id: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Accept only a complete terminal envelope, never accumulated text deltas."""
    data: list[bytes] = []
    event_bytes = 0
    total_bytes = 0
    response_id = None
    while True:
        if time.perf_counter() >= deadline:
            raise TimeoutError("Responses stream deadline exceeded")
        socket = getattr(
            getattr(getattr(response, "fp", None), "raw", None), "_sock", None
        )
        if socket is not None:
            socket.settimeout(max(0.001, deadline - time.perf_counter()))
        line = response.readline(4 * 1024 * 1024 + 1)
        total_bytes += len(line)
        if len(line) > 4 * 1024 * 1024 or total_bytes > 16 * 1024 * 1024:
            raise ResponsesStreamError("Responses stream exceeded its byte limit")
        if not line:
            raise ResponsesStreamError(
                "Responses stream ended without a terminal event"
            )
        line = line.rstrip(b"\r\n")
        if line.startswith(b"data:"):
            part = line[5:].lstrip(b" ")
            data.append(part)
            event_bytes += len(part)
            if event_bytes > 4 * 1024 * 1024:
                raise ResponsesStreamError("Responses event exceeded its byte limit")
        elif not line and data:
            raw = b"\n".join(data)
            data, event_bytes = [], 0
            if raw == b"[DONE]":
                raise ResponsesStreamError("Responses stream lacks a terminal response")
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ResponsesStreamError(
                    "Responses stream event is invalid JSON"
                ) from exc
            if not isinstance(event, dict):
                raise ResponsesStreamError("Responses stream event is not an object")
            kind = event.get("type")
            envelope = event.get("response")
            identifier = envelope.get("id") if isinstance(envelope, dict) else None
            if (
                on_response_id
                and isinstance(identifier, str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", identifier)
            ):
                if response_id is not None and identifier != response_id:
                    raise ResponsesStreamError(
                        "Responses stream changed response identity"
                    )
                response_id = identifier
                on_response_id(identifier)
            if not isinstance(kind, str):
                raise ResponsesStreamError("Responses event type is invalid")
            terminal = {
                "response.completed": "completed",
                "response.failed": "failed",
                "response.incomplete": "incomplete",
            }
            if kind in terminal:
                envelope = event.get("response")
                if (
                    not isinstance(envelope, dict)
                    or envelope.get("status") != terminal[kind]
                ):
                    raise ResponsesStreamError(
                        "Responses terminal status is inconsistent"
                    )
                return envelope
            if kind == "error":
                raise ResponsesStreamError(
                    "Responses stream reported an upstream error"
                )


def responses_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    messages = []
    for message in payload["messages"]:
        content = message["content"]
        if isinstance(content, list):
            parts = []
            for part in content:
                if part["type"] == "text":
                    parts.append({"type": "input_text", "text": part["text"]})
                elif part["type"] == "image_url":
                    image = part["image_url"]
                    parts.append(
                        {
                            "type": "input_image",
                            "image_url": image["url"],
                            "detail": image.get("detail", "high"),
                        }
                    )
                else:
                    raise ValueError("Unsupported planner content part.")
            content = parts
        messages.append({"role": message["role"], "content": content})
    output_format = payload["response_format"]
    if output_format["type"] == "json_schema":
        output_format = {"type": "json_schema", **output_format["json_schema"]}
    result = {
        "model": payload["model"],
        "input": messages,
        "text": {"format": output_format},
        "store": False,
        "stream": True,
    }
    if "max_completion_tokens" in payload:
        result["max_output_tokens"] = payload["max_completion_tokens"]
    return result


def responses_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep IDs/usage/status and expose only assistant output text to parsers."""
    texts: list[str] = []
    refused = False
    output = payload.get("output")
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, Mapping):
                continue
            if part.get("type") == "refusal":
                refused = True
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    status = payload.get("status")
    details = payload.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, Mapping) else None
    finish = "unknown"
    if refused or reason == "content_filter":
        finish = "content_filter"
    elif status == "completed":
        finish = "stop"
    elif reason == "max_output_tokens":
        finish = "length"
    return {
        **payload,
        "_native_responses": True,
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": "".join(texts)
                    if status == "completed" and not refused
                    else None,
                },
            }
        ],
    }
