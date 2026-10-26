"""Bounded provider receipts, excluding credentials and image/request bodies."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def safe_text(value: str, limit: int = 1200) -> str:
    value = re.sub(r"data:[^\s\"']+", "[image omitted]", value)
    value = re.sub(r"https?://[^\s\"']+", "[url omitted]", value)
    value = re.sub(r"\b(?:sk|rk)-[\w-]+", "[credential omitted]", value)
    value = re.sub(r"(?i)bearer\s+[^\s,;\"']+", "Bearer [omitted]", value)
    value = re.sub(
        r"(?i)((?:api[_-]?key|authorization|password|secret|access[_-]?token)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+",
        r"\1[omitted]",
        value,
    )
    return value[:limit]


def error_summary(payload: Mapping[str, Any]) -> dict[str, str]:
    error = payload.get("error")
    if isinstance(error, Mapping):
        result = {
            key: safe_text(str(error[key]), 1200 if key == "message" else 255)
            for key in ("code", "type", "message", "param")
            if isinstance(error.get(key), (str, int)) and str(error[key])
        }
        return result or {"code": "provider_error"}
    if isinstance(error, str):
        return {"code": "provider_error", "message": safe_text(error)}
    message = payload.get("message")
    return {
        "code": "provider_error",
        **({"message": safe_text(message)} if isinstance(message, str) else {}),
    }


def known_image_route_rejection(status: int, payload: Mapping[str, Any]) -> bool:
    error = payload.get("error")
    if (
        status != 400
        or not isinstance(error, Mapping)
        or any(
        payload.get(key) for key in (
            "data", "images", "output", "url", "b64_json", "generation_id", "task_id"
        )
        )
    ):
        return False
    code = error.get("code")
    if code == "upstream_text_reply":
        return error.get("type") == "invalid_request_error"
    return code in {
        "model_not_found",
        "unsupported_model",
        "model_not_supported",
        "channel_unavailable",
        "no_available_channel",
    }


def retained_metrics(raw_usage: object) -> dict[str, Any]:
    """Defend at the adapter/persistence boundary as well as the gateway."""
    metrics = raw_usage.get("metrics") if isinstance(raw_usage, Mapping) else None
    if not isinstance(metrics, Mapping):
        return {}
    result: dict[str, Any] = {}
    error = metrics.get("provider_error")
    if isinstance(error, Mapping):
        result["provider_error"] = error_summary({"error": error})
    attempts = metrics.get("provider_attempts")
    if isinstance(attempts, list):
        result["provider_attempts"] = [
            {
                key: safe_text(str(value), 255) if isinstance(value, str) else value
                for key, value in row.items()
                if key in {"route", "host", "model", "http_status", "request_id"}
                and (value is None or type(value) in {str, int})
            }
            | (
                {"error": error_summary({"error": row["error"]})}
                if isinstance(row.get("error"), Mapping)
                else {}
            )
            for row in attempts[:4]
            if isinstance(row, Mapping)
        ]
    return result
