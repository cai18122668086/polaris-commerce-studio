"""Windows copy-mode compatibility, strictly limited to task-local copies."""

import atexit
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any, cast
from uuid import uuid4


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

    def receipt() -> None:
        if copied:
            directory = root / "compatibility"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"copies-{os.getpid()}-{uuid4().hex[:8]}.json").write_text(
                json.dumps(
                    {
                        "version": "task-copy-permissions/2",
                        "native_sources_changed": False,
                        "writable_task_copies": sorted(copied),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    atexit.register(receipt)
