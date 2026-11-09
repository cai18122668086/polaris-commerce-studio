"""Reuse bundled font coverage in audited original subtitle subprocesses."""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from .motion_library import read_json, sha256
from .motion_local_dependencies import dependency_state, local_dependencies
from .video_editing_subtitle_foreground import FOREGROUND_SUBTITLE_DEPENDENCIES

_SUBTITLES = Path("src/engines/workspace/字幕动效_可编辑库_20261105")
_NATIVE = Path("commercial_runtime/native.py")
_CORE = _SUBTITLES / "SG-production/core.py"
_BG_PRODUCTION = _SUBTITLES / "SG-BG-production/production.py"
_ENTRY_DIGESTS = {
    **dict.fromkeys(
        ("SG-S03", "SG-S04", "SG-S06", "SG-S08", "SG-S09"),
        "9fda50a11d6abf2fc1e7c51e34b0ef75015c732b07fd1704218b8f20b0d3075c",
    ),
    "SG-S02": "87274b5e410831638782fbe4bb3c241b3e546a29d8a32ba3832bf67a25ce68ed",
    "SG-S01": "940fc34a86e7f24d89a87a74bf5651a60fdab31f79ccf8b2ce337d32a7685063",
    "SG-S05": "f607310f0a0010a9d15c1e9fe12e49c3764999573b5d037ad153f286d6770d8e",
    "SG-S07": "c8ddd2b750fa39b6115efd62a7a82d7d71c9d95dcc59d1a806a101ed671356e6",
    "SG-S10": "3ebc549e6eefe28a4c0cb35f5b6af79c2ccf4352d2b01cdd0a137eb5b7dfd712",
    **dict.fromkeys(
        ("BG-S06", "BG-S07", "BG-S08"),
        "03636383dc5b06001f3335b81c2e27929204874d2d47fb15412971595fb577d6",
    ),
}
_SOURCES = {
    _NATIVE: "2b1c213087a59ada597fda3d9fd7c412b857d920fb04635278ae180b46bfafea",
    _CORE: "7755fe9dd4cc000001d7e64366aac4e44036ab6734e0bfa2ef946529ccfe2d79",
    _SUBTITLES / "SG-production/mechanisms.py": (
        "48cd8bf1afd634da9fee47a372048f541902112480ad9fce054d825dcc4bcd9f"
    ),
}


def _font_reader(
    font_root: Path, exact_bindings: frozenset[Path] = frozenset()
) -> type[TTFont]:
    maps: dict[tuple[Path, int, int, int, int, int, int], dict[int, str] | None] = {}

    class NativeCoverageFont(TTFont):
        def __init__(self, file: str, *, fontNumber: int, lazy: bool) -> None:
            super().__init__(file, fontNumber=fontNumber, lazy=lazy)
            self._coverage_key = None
            path = Path(file).resolve()
            if (
                lazy
                and self.reader is not None
                and (path.is_relative_to(font_root) or path in exact_bindings)
            ):
                st = os.fstat(self.reader.file.fileno())
                self._coverage_key = (
                    path,
                    fontNumber,
                    st.st_dev,
                    st.st_ino,
                    st.st_size,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                )

        def getBestCmap(self) -> dict[int, str] | None:
            # The pinned core only tests codepoint membership in this map.
            key = self._coverage_key
            if key is None:
                return super().getBestCmap()
            if key not in maps:
                if len(maps) == 12:
                    maps.clear()
                maps[key] = super().getBestCmap()
            return maps[key]

    return NativeCoverageFont


def install_native_font_maps(package: Path, root: Path) -> None:
    if "--job" in sys.argv:
        job = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
        if job.parent != root / "plans":
            return
    elif len(sys.argv) == 2:
        job = Path(sys.argv[1]).resolve()
        if job.parent != root / "layout" or not job.match("role-job-*.json"):
            return
    else:
        return
    group = read_json(job)["group_id"]
    if group not in _ENTRY_DIGESTS:
        return
    entry = _SUBTITLES / group / "render.py"
    sources = {**_SOURCES, entry: _ENTRY_DIGESTS[group]}
    if group in {"BG-S06", "BG-S07", "BG-S08"}:
        sources[_BG_PRODUCTION] = (
            "0a4732fed7c52585bb82fd4b7a8a8235599bee15167e95e9beb585f1ede83d09"
        )
    if any(
        not (package / path).is_file() or sha256(package / path) != digest
        for path, digest in sources.items()
    ):
        return

    sys.path.insert(0, str(package))
    try:
        native: Any = importlib.import_module("commercial_runtime.native")
    finally:
        sys.path.pop(0)
    if Path(native.__file__).resolve() != package / _NATIVE:
        return
    load_module = native.module
    exact_bindings: frozenset[Path] = frozenset()
    if group == "SG-S05":
        registered = local_dependencies(root / "bindings.json")
        identities = {
            row["id"]: row
            for row in read_json(package / "catalog/external-resources.json")[
                "resources"
            ]
        }
        exact_bindings = frozenset(
            Path(registered[rid]).resolve()
            for rid in FOREGROUND_SUBTITLE_DEPENDENCIES[group]
            if dependency_state(identities[rid], registered.get(rid)) == "verified"
        )
    reader = _font_reader((package / "assets/fonts").resolve(), exact_bindings)

    def load(path: str | Path, name: str = "motion_native") -> Any:
        module = load_module(path, name)
        if Path(path).resolve() == package / entry:
            core = sys.modules.get("core")
            if (
                core is not None
                and Path(core.__file__ or "").resolve() == package / _CORE
            ):
                core.__dict__["TTFont"] = reader
        return module

    native.module = load
