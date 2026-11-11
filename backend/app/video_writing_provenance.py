"""Track the adopted writing documents for an unchanged spoken script."""

import hashlib
from typing import Any

from pydantic import ValidationError

from .video_studio_schemas import VideoWritingOrigin


def spoken_script(content: dict) -> str | None:
    draft = content.get("draft", {})
    text = draft.get("text")
    return text if isinstance(text, str) and draft.get("drive") != "audio" else None


def script_digest(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def matching_writing_origin(
    origin: dict | None, content: dict
) -> dict[str, Any] | None:
    if origin is None:
        return None
    if origin.get("script_sha256") != script_digest(spoken_script(content)):
        return None
    try:
        return VideoWritingOrigin.model_validate(origin).model_dump(mode="json")
    except ValidationError:
        return None
