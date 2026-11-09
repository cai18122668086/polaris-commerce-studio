"""Reuse the original SG-S09 font coverage within one native subprocess."""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from .motion_library import read_json, sha256

_SUBTITLES = Path("src/engines/workspace/字幕动效_可编辑库_20261105")
_NATIVE = Path("commercial_runtime/native.py")
_ENTRY = _SUBTITLES / "SG-S09/render.py"
_SOURCES = {
    _NATIVE: "2b1c213087a59ada597fda3d9fd7c412b857d920fb04635278ae180b46bfafea",
    _ENTRY: "9fda50a11d6abf2fc1e7c51e34b0ef75015c732b07fd1704218b8f20b0d3075c",
    _SUBTITLES / "SG-production/core.py": (
        "7755fe9dd4cc000001d7e64366aac4e44036ab6734e0bfa2ef946529ccfe2d79"
    ),
    _SUBTITLES / "SG-production/mechanisms.py": (
        "48cd8bf1afd634da9fee47a372048f541902112480ad9fce054d825dcc4bcd9f"
    ),
}


def _font_reader(font_root: Path) -> type[TTFont]:
    maps: dict[tuple[Path, int, int, int, int, int, int], dict[int, str] | None] = {}

    class NativeCoverageFont(TTFont):
        def __init__(self, file: str, *, fontNumber: int, lazy: bool) -> None:
            super().__init__(file, fontNumber=fontNumber, lazy=lazy)
            self._coverage_key = None
            path = Path(file).resolve()
            if lazy and path.is_relative_to(font_root) and self.reader is not None:
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


def install_sg_s09_font_maps(package: Path, root: Path) -> None:
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
    if read_json(job)["group_id"] != "SG-S09":
        return
    if any(
        not (package / path).is_file() or sha256(package / path) != digest
        for path, digest in _SOURCES.items()
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
    reader = _font_reader((package / "assets/fonts").resolve())

    def load(path: str | Path, name: str = "motion_native") -> Any:
        module = load_module(path, name)
        if Path(path).resolve() == package / _ENTRY:
            module.validate.__globals__["TTFont"] = reader
        return module

    native.module = load
