"""Provider-published genders for imported public models; never infer from photos."""

import json
from pathlib import Path

_CATALOG = json.loads(
    (Path(__file__).parent / "data/quanyu-system-avatar-genders.json").read_text(
        encoding="utf-8"
    )
)
_MODELS = {row["model_id"]: row for row in _CATALOG["models"]}


def public_avatar_gender(model_id: int | None, name: str, current: str = "未知") -> str:
    if current in {"男", "女"}:
        return current
    row = _MODELS.get(model_id)
    if row and row["model_name"] == name:
        return str(row["gender"])
    return "未知"
