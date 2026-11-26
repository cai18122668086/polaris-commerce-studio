"""Server capabilities a template needs, checked before any paid planning.

A template whose installed renderer needs the presenter matte model, or whose
signature style groups all miss their fonts/originals, cannot finish on this
server. Users must learn that before the paid planning call, and the picker
must not offer it.
"""

from __future__ import annotations

import hashlib
from functools import cache, lru_cache
from pathlib import Path

from .config import Settings
from .motion_local_dependencies import read_dependency_manifest, resolve_local_binding

FOREGROUND_UNAVAILABLE = "此模板需要人物抠像能力，当前服务暂未开通，请选择其他模板。"
STYLE_UNAVAILABLE = "此模板的招牌画面所需字体或原件暂未就绪，请选择其他模板。"


@lru_cache(maxsize=64)
def _digest(path: str, size: int, mtime_ns: int) -> str:
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_matches(path: str | Path | None, expected: str) -> bool:
    """Hash a read-only resource once per file revision."""
    if not path:
        return False
    try:
        stat = Path(path).stat()
        if not Path(path).is_file():
            return False
        return _digest(str(path), stat.st_size, stat.st_mtime_ns) == expected
    except OSError:
        return False


def foreground_available(settings: Settings) -> bool:
    from .bihuo_suite.foreground import MODEL_ID, MODEL_SHA

    manifest = settings.video_editing_native_bindings_file
    try:
        bindings = read_dependency_manifest(manifest)
    except (OSError, ValueError):
        return False
    resources = bindings.get("resources")
    if not isinstance(resources, dict):
        return False
    return file_matches(
        resolve_local_binding(manifest, resources.get(MODEL_ID)), MODEL_SHA
    )


def suite_template_blocker(template_id: str | None, settings: Settings) -> str | None:
    """Chinese reason a full-suite template cannot render here, else None."""
    from .bihuo_suite.registry import definition, is_template

    if not is_template(template_id):
        return None
    assert template_id is not None
    if definition(template_id).get("requires_foreground") and not foreground_available(
        settings
    ):
        return FOREGROUND_UNAVAILABLE
    return None


def overlay_style_blocker(template: dict, settings: Settings) -> str | None:
    """Server-wide (not per-project) style blocker for an overlay template."""
    from .motion_local_dependencies import dependency_state, local_dependencies
    from .video_editing_catalog import (
        external_dependencies,
        unavailable_template_groups,
    )
    from .video_editing_template_styles import STYLES

    profile = STYLES.get(template["id"]) or {}
    signature = set(profile.get("signature_group_ids") or [])
    if not signature or settings.video_editing_library_dir is None:
        return None
    try:
        external = external_dependencies(settings.video_editing_library_dir)
    except (OSError, ValueError, KeyError):
        return None
    bindings = local_dependencies(settings.video_editing_native_bindings_file)

    @cache
    def state(rid: str) -> str:
        identity = external.get(rid, {})
        binding = bindings.get(rid)
        if binding and identity.get("sha256"):
            return (
                "verified"
                if file_matches(binding, identity["sha256"])
                and identity.get("kind") in {"font", "model"}
                else "identity_mismatch"
            )
        return dependency_state(identity, binding)

    unavailable = unavailable_template_groups(template, state)  # type: ignore[arg-type]
    return STYLE_UNAVAILABLE if signature <= set(unavailable) else None
