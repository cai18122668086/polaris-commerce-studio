"""Install one portable suite bundle; keep rendered examples in the example store.

Usage: python tools/install_bihuo_template.py <delivery/website-v1>
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def install(
    source: Path,
    target: Path,
    *,
    replace: bool = False,
    manifest_name: str = "bundle.json",
) -> None:
    if Path(manifest_name).name != manifest_name:
        raise ValueError("Manifest must be a file in the bundle directory")
    source_manifest = source / manifest_name
    manifest = json.loads(source_manifest.read_text("utf-8"))
    if manifest["schema"] != "tengli.bihuo-runtime-bundle/1":
        raise ValueError("Invalid suite bundle schema")
    ready = (target / "bundle.json").is_file()
    if (
        ready
        and (target / "bundle.json").read_bytes() == source_manifest.read_bytes()
    ):
        return
    if ready and not replace:
        raise ValueError(
            "Suite already installed; pass --replace for a versioned update"
        )
    # Stage all validated resources before changing the installed directory.
    revision = hashlib.sha256(source_manifest.read_bytes()).hexdigest()[:16]
    stage = target.with_name(target.name + ".installing-" + revision)
    if (
        stage.exists()
        and (stage / "bundle.json").is_file()
        and (stage / "bundle.json").read_bytes() != source_manifest.read_bytes()
    ):
        raise ValueError("Unfinished installation belongs to a different bundle")
    stage.mkdir(parents=True, exist_ok=True)
    for relative, digest in manifest["files"].items():
        original = (source / relative).resolve()
        if not original.is_relative_to(source.resolve()) or not original.is_file():
            raise ValueError("Invalid suite resource path")
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError("Suite resource changed: " + relative)
        output = stage / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if (
            output.is_file()
            and hashlib.sha256(output.read_bytes()).hexdigest() == digest
        ):
            continue
        shutil.copy2(original, output)
    shutil.copy2(source_manifest, stage / "bundle.json")
    if ready:
        repository = Path(__file__).resolve().parents[1]
        history = (
            repository
            / ".local/bihuo-bundles"
            / (
                target.name
                + "-"
                + hashlib.sha256((target / "bundle.json").read_bytes()).hexdigest()[:16]
            )
        )
        if not target.resolve().is_relative_to(
            repository
        ) or not history.resolve().is_relative_to(repository):
            raise ValueError("Bundle update escaped its repository")
        history.parent.mkdir(parents=True, exist_ok=True)
        # Windows font handles may keep the installed directory open. Preserve
        # it by copying, then replace only changed resources and the index last.
        if not history.exists():
            shutil.copytree(target, history)
        for relative, digest in manifest["files"].items():
            current = target / relative
            if (
                current.is_file()
                and hashlib.sha256(current.read_bytes()).hexdigest() == digest
            ):
                continue
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / relative, current)
        shutil.copy2(stage / "bundle.json", target / "bundle.json")
        return
    try:
        stage.rename(target)
    except (PermissionError, FileExistsError):
        # Windows recursive file watchers can deny directory renames. A suite
        # stays unavailable until its validated manifest is copied last.
        target.mkdir(parents=True, exist_ok=True)
        for relative in manifest["files"]:
            current = target / relative
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / relative, current)
        shutil.copy2(stage / "bundle.json", target / "bundle.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--manifest", default="bundle.json")
    args = parser.parse_args()
    source = args.source.resolve()
    target = (
        Path(__file__).resolve().parents[1]
        / "backend/app/bihuo_suite/templates"
        / source.parents[1].name
    )
    install(source, target, replace=args.replace, manifest_name=args.manifest)
    print("Installed", target.name)


if __name__ == "__main__":
    main()
