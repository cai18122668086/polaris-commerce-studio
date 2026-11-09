"""Native compatibility for task-local copies and immutable bundled fonts."""

import atexit
import hashlib
import importlib
import json
import os
import shutil
import stat
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from PIL import ImageFont

_OFFSET_INSENSITIVE_MATTE_GROUPS = {
    *(f"AZL{number:02}" for number in range(1, 8)),
    "YYO02",
    "YYO07",
    *(f"YY6O{number:02}" for number in range(3, 7)),
}


def isolate_native_matte_cache(package: Path, root: Path) -> None:
    """Keep the original offset-insensitive matte keys local to each shot."""
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = job_path.read_bytes()
    if json.loads(job)["group_id"] not in _OFFSET_INSENSITIVE_MATTE_GROUPS:
        return
    sys.path.insert(0, str(package))
    try:
        paths = importlib.import_module("commercial_runtime.paths")
    finally:
        sys.path.pop(0)
    source = paths.__file__
    if (
        source is None
        or Path(source).resolve() != package / "commercial_runtime/paths.py"
    ):
        raise ValueError("Native matte cache must use the pinned original runtime")
    original_cache_path = paths.cache_path
    shot = hashlib.sha256(job).hexdigest()

    def cache_path(base: str | Path, name: str = "cache") -> Path:
        if name == "cache/mattes":
            base = Path(base) / shot
        return original_cache_path(base, name)

    cast(Any, paths).cache_path = cache_path


def install(package: Path, root: Path) -> None:
    package, root = package.resolve(), root.resolve()
    if root.is_relative_to(package):
        raise ValueError("Task copies must remain outside the original library")
    original_copy, original_tree = shutil.copy2, shutil.copytree
    copied: set[str] = set()

    def authorized(source: Any, destination: Any) -> bool:
        return Path(source).resolve().is_relative_to(package) and Path(
            destination
        ).resolve().is_relative_to(root)

    def instance_copy(source: Any, destination: Any, *args: Any, **kwargs: Any) -> Any:
        src, dst = Path(source).resolve(), Path(destination).resolve()
        if dst.is_dir():
            dst = dst / src.name
        task_copy = authorized(src, dst)
        if task_copy and dst.exists():
            dst.chmod(dst.stat().st_mode | stat.S_IWUSR)
        result = original_copy(source, destination, *args, **kwargs)
        if task_copy:
            dst.chmod(dst.stat().st_mode | stat.S_IWUSR)
            copied.add(dst.relative_to(root).as_posix())
        return result

    def instance_tree(
        src: Any,
        dst: Any,
        symlinks: bool = False,
        ignore: Any = None,
        copy_function: Any = None,
        ignore_dangling_symlinks: bool = False,
        dirs_exist_ok: bool = False,
    ) -> Any:
        function = copy_function or original_copy
        if authorized(src, dst) and function is original_copy:
            function = instance_copy
        return original_tree(
            src,
            dst,
            symlinks,
            ignore,
            function,
            ignore_dangling_symlinks,
            dirs_exist_ok,
        )

    cast(Any, shutil).copy2 = instance_copy
    cast(Any, shutil).copytree = instance_tree

    original_font = ImageFont.truetype
    font_root = package / "assets" / "fonts"

    @lru_cache(maxsize=12)
    def bundled_font(
        path: str, size: float, index: int, encoding: str, layout_engine: Any
    ) -> ImageFont.FreeTypeFont:
        return original_font(path, size, index, encoding, layout_engine)

    def load_font(
        font: Any,
        size: float = 10,
        index: int = 0,
        encoding: str = "",
        layout_engine: Any = None,
    ) -> ImageFont.FreeTypeFont:
        # The pinned original subtitle renderers only read these fonts. On
        # Windows, Pillow otherwise re-reads Unicode paths into memory per call.
        if os.name == "nt" and isinstance(font, (str, Path)):
            path = Path(font)
            if path.is_absolute() and path.is_relative_to(font_root):
                return bundled_font(str(path), size, index, encoding, layout_engine)
        return original_font(font, size, index, encoding, layout_engine)

    if os.name == "nt":
        cast(Any, ImageFont).truetype = load_font

    def receipt() -> None:
        cache = bundled_font.cache_info()
        if copied or cache.hits:
            directory = root / "compatibility"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"copies-{os.getpid()}-{uuid4().hex[:8]}.json").write_text(
                json.dumps(
                    {
                        "version": "task-copy-permissions/2",
                        "native_sources_changed": False,
                        "writable_task_copies": sorted(copied),
                        "bundled_font_reuses": cache.hits,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    atexit.register(receipt)
