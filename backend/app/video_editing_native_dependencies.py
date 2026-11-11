"""Preflight original dependencies for each shot in a saved native plan."""

from functools import cached_property
from pathlib import Path
from typing import Any

from .motion_browser_originals import (
    BROWSER_ORIGINALS_REQUIRED,
    require_drawn_browser_assets,
)
from .motion_library import read_json
from .motion_local_dependencies import (
    component_use_state,
    dependency_state,
    local_dependencies,
)
from .video_editing_browser_boot import (
    BROWSER_BOOT_FONT_GROUPS,
    BROWSER_BOOT_FONTS_REQUIRED,
    BrowserBootFontsMissing,
    require_browser_boot_fonts,
)
from .video_editing_browser_rotation import STRIP_CARD_GROUP, TEXTURE_WORD_GROUP
from .video_editing_hypit_label_cards import LABEL_CARD_GROUP

ORIGINAL_DEPENDENCY_REQUIRED = "EDITING_ORIGINAL_NATIVE_DEPENDENCY_REQUIRED"
_DRAWN_GROUPS = frozenset((STRIP_CARD_GROUP, TEXTURE_WORD_GROUP))


class NativeDependencyError(ValueError):
    def __init__(self, resource_id: str, reason: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"{reason}: {resource_id}")


def recipe_dependency_paths(recipe: dict, registered: dict[str, str]) -> dict[str, str]:
    direct = recipe.get("dependency_bindings", {})
    dependency_ids = recipe.get("dependency_ids", [])
    if (
        not isinstance(direct, dict)
        or any(
            not isinstance(rid, str) or not isinstance(path, str)
            for rid, path in direct.items()
        )
        or not isinstance(dependency_ids, list)
        or any(not isinstance(rid, str) for rid in dependency_ids)
        or len(set(dependency_ids)) != len(dependency_ids)
        or set(dependency_ids) & set(direct)
    ):
        raise ValueError("Choose a single explicit binding per original dependency")
    for rid in dependency_ids:
        if rid not in registered:
            raise NativeDependencyError(
                rid, "Selected original dependency is not registered on this host"
            )
    return {**direct, **{rid: registered[rid] for rid in dependency_ids}}


def verified_recipe_dependency(
    identity: dict, path: str, resource_id: str, group_id: str, manifest: Path | None
) -> str:
    source = str(Path(path).resolve())
    if dependency_state(identity, source) != "verified":
        raise NativeDependencyError(
            resource_id, "Original font/model dependency bytes do not match"
        )
    usage = component_use_state(identity, manifest)
    if usage is not None and (
        group_id != LABEL_CARD_GROUP or usage != "reference_recorded"
    ):
        raise NativeDependencyError(
            resource_id, "Restricted original font needs a component use reference"
        )
    return source


class NativeDependencyPreflight:
    """Share file checks across candidates in one request, and recheck on submission."""

    def __init__(self, package: Path, manifest: Path | None) -> None:
        self.package = package
        self.manifest = manifest
        self._resolved: dict[tuple[str, str, str], str] = {}
        self._drawn: dict[str, bool] = {}
        self._boot: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[str, ...]] = {}

    @cached_property
    def registered(self) -> dict[str, str]:
        return local_dependencies(self.manifest)

    @cached_property
    def identities(self) -> dict[str, dict]:
        return {
            row["id"]: row
            for row in read_json(self.package / "catalog/external-resources.json")[
                "resources"
            ]
        }

    @cached_property
    def groups(self) -> dict[str, dict]:
        return {
            row["id"]: row
            for row in read_json(self.package / "catalog/groups.json")["groups"]
        }

    def _resolved_paths(self, group_id: str, recipe: dict) -> dict[str, str]:
        resolved = {}
        for rid, path in recipe_dependency_paths(recipe, self.registered).items():
            key = group_id, rid, path
            if key not in self._resolved:
                self._resolved[key] = verified_recipe_dependency(
                    self.identities.get(rid, {}), path, rid, group_id, self.manifest
                )
            resolved[rid] = self._resolved[key]
        return resolved

    def _drawn_ready(self, group_id: str) -> bool:
        if group_id not in self._drawn:
            try:
                require_drawn_browser_assets(self.package, group_id, self.manifest)
            except (OSError, ValueError, KeyError, TypeError):
                self._drawn[group_id] = False
            else:
                self._drawn[group_id] = True
        return self._drawn[group_id]

    def _missing_boot(self, group_id: str, resolved: dict[str, str]) -> tuple[str, ...]:
        key = group_id, tuple(sorted(resolved.items()))
        if key not in self._boot:
            try:
                require_browser_boot_fonts(
                    self.package, self.groups[group_id], {**self.registered, **resolved}
                )
            except BrowserBootFontsMissing as error:
                self._boot[key] = tuple(error.states)
            except (OSError, ValueError, KeyError, TypeError):
                self._boot[key] = ("原生字体加载器",)
            else:
                self._boot[key] = ()
        return self._boot[key]

    def blocker(self, group_id: str, recipe: dict[str, Any]) -> tuple[str, str] | None:
        if group_id in _DRAWN_GROUPS and not self._drawn_ready(group_id):
            return (
                BROWSER_ORIGINALS_REQUIRED,
                f"{group_id} 缺少经校验的原模板底板或纹理。",
            )
        try:
            resolved = self._resolved_paths(group_id, recipe)
        except NativeDependencyError as error:
            return (
                ORIGINAL_DEPENDENCY_REQUIRED,
                f"{group_id} 无法核验原库依赖 {error.resource_id}。",
            )
        except (OSError, ValueError, KeyError, TypeError):
            return ORIGINAL_DEPENDENCY_REQUIRED, f"{group_id} 的原库依赖记录无法核验。"
        if group_id in BROWSER_BOOT_FONT_GROUPS:
            missing = self._missing_boot(group_id, resolved)
            if missing:
                return (
                    BROWSER_BOOT_FONTS_REQUIRED,
                    f"{group_id} 无法核验原库启动字体（{'、'.join(missing)}）。",
                )
        return None
