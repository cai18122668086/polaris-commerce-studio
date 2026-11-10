"""Readiness probes for the opt-in editing runtime, independent of the queue."""

import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .config import Settings
from .motion_library import verify_package
from .video_editing_funasr import bundle_identity
from .video_editing_hypit import hypit_tools
from .video_editing_pipeline import environment

_NATIVE_IMPORTS = (
    "PIL.Image",
    "cv2",
    "numpy",
    "onnxruntime",
    "fontTools.ttLib",
    "jsonschema",
    "playwright",
)


def _check_mounts(settings: Settings) -> dict[str, bool]:
    library = settings.video_editing_library_dir.resolve()
    tasks = settings.video_editing_tasks_dir.resolve()
    if tasks.is_relative_to(library) or not settings.video_media_dir.is_dir():
        raise ValueError("Editing volumes have incorrect roots")
    with TemporaryDirectory(prefix=".editing-check-", dir=tasks) as temporary:
        probe = Path(temporary) / "probe"
        probe.write_bytes(b"editing volume probe")
        if probe.read_bytes() != b"editing volume probe":
            raise OSError("Editing volume readback failed")
    return {"tasks_writable": True, "video_media_directory_present": True}


def _command(arguments: list[str], settings: Settings) -> str:
    result = subprocess.run(
        arguments,
        env=environment(settings),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    return result.stdout


def _check_media(settings: Settings) -> dict[str, str]:
    ffmpeg, ffprobe = settings.video_editing_ffmpeg, settings.video_editing_ffprobe
    filters = _command([ffmpeg, "-hide_banner", "-filters"], settings)
    encoders = _command([ffmpeg, "-hide_banner", "-encoders"], settings)
    if not {"subtitles", "overlay", "amix"} <= set(filters.split()):
        raise ValueError("FFmpeg lacks required editing filters")
    if not {"libx264", "aac"} <= set(encoders.split()):
        raise ValueError("FFmpeg lacks required delivery encoders")
    return {
        "ffmpeg": _command([ffmpeg, "-version"], settings).splitlines()[0],
        "ffprobe": _command([ffprobe, "-version"], settings).splitlines()[0],
    }


def _check_python(settings: Settings) -> dict[str, str]:
    script = (
        "import importlib, sys; "
        "[importlib.import_module(name) for name in sys.argv[1:]]; "
        "print(sys.version.split()[0])"
    )
    output = _command(
        [settings.video_editing_python, "-B", "-c", script, *_NATIVE_IMPORTS],
        settings,
    )
    return {"native_python": output.strip()}


def _check_browser(
    settings: Settings, browser_path: str | None = None
) -> dict[str, str]:
    from playwright.sync_api import sync_playwright

    browser_path = browser_path or shutil.which("chrome")
    if not browser_path and os.name == "nt":
        browser_path = next(
            (
                str(path)
                for name in ("PROGRAMFILES", "PROGRAMFILES(X86)")
                if (base := os.environ.get(name))
                and (
                    path := Path(base) / "Google/Chrome/Application/chrome.exe"
                ).is_file()
            ),
            None,
        )
    browser_environment: dict[str, str | float | bool] = {**environment(settings)}
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            headless=True, executable_path=browser_path, env=browser_environment
        )
        try:
            page = browser.new_page()
            actual = page.evaluate(
                """() => {
                    const ctx = document.createElement('canvas').getContext('2d');
                    ctx.fillStyle = '#112233';
                    ctx.fillRect(0, 0, 1, 1);
                    return Array.from(ctx.getImageData(0, 0, 1, 1).data);
                }"""
            )
            if actual != [17, 34, 51, 255]:
                raise ValueError("Browser canvas probe failed")
            return {"chromium": browser.version}
        finally:
            browser.close()


def _check_asr(settings: Settings) -> dict[str, str]:
    root = Path(settings.video_editing_asr_model)
    if settings.video_editing_asr_provider == "funasr":
        importlib.import_module("funasr")
        return {"provider": "funasr", "model_manifest_sha256": bundle_identity(root)}
    importlib.import_module("faster_whisper")
    if not all(
        (root / name).is_file()
        for name in ("model.bin", "config.json", "tokenizer.json")
    ):
        raise ValueError("Select a local faster-whisper model for offline verification")
    return {"provider": "faster-whisper", "local_model": "present"}


def _check_alignment(settings: Settings) -> dict[str, str]:
    from .video_editing_alignment import ALIGNMENT_MANIFEST

    return {
        "model_manifest_sha256": bundle_identity(
            settings.video_editing_alignment_model_dir, manifest_path=ALIGNMENT_MANIFEST
        )
    }


def _check_hypit(settings: Settings) -> dict[str, str]:
    tools = hypit_tools(settings, settings.video_editing_hypit_internal_workspace)
    cli = _command(["node", tools["hypit_module"], "--version"], settings).strip()
    if not cli:
        raise ValueError("The configured Hypit CLI returned no version")
    return {
        "scope": "internal_workspace",
        "cli": cli,
        **_check_browser(settings, tools["chrome"]),
    }


def check_editing_runtime(settings: Settings) -> dict[str, Any]:
    checks: dict[str, Callable[[Settings], Any]] = {
        "mounts": _check_mounts,
        "library": lambda cfg: verify_package(cfg.video_editing_library_dir),
        "python": _check_python,
        "media": _check_media,
        "browser": _check_browser,
        "asr": _check_asr,
    }
    if settings.video_editing_alignment_enabled:
        checks["alignment"] = _check_alignment
    if (
        settings.video_editing_hypit_internal_workspace
        or settings.video_editing_hypit_local_module
        or settings.video_editing_hypit_local_chrome
    ):
        checks["hypit"] = _check_hypit
    results = {}
    for name, check in checks.items():
        try:
            results[name] = {"status": "passed", "details": check(settings)}
        except Exception as error:
            # Raw subprocess output and settings can contain local paths or keys.
            results[name] = {"status": "failed", "error_type": type(error).__name__}
    return {
        "ready": all(row["status"] == "passed" for row in results.values()),
        "checks": results,
    }


def print_editing_runtime(settings: Settings) -> None:
    with redirect_stdout(sys.stderr):
        report = check_editing_runtime(settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        sys.exit(1)
