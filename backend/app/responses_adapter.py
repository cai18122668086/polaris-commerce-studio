"""Translate our stateless vision calls to the native Responses wire format."""

from collections.abc import Mapping
from typing import Any


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
