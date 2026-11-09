import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import video_editing_native_compat as compat
from app.config import Settings
from app.motion_library import atomic_json, sha256
from app.video_editing_pipeline import environment


def test_native_subprocess_keeps_worker_browser_path_without_provider_credentials(
    monkeypatch, tmp_path
):
    browsers = str(tmp_path / "chromium")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", browsers)
    monkeypatch.setenv("POLARIS_VIDEO_SCRIPT_API_KEY", "test-only-provider-sentinel")

    child = environment(Settings())
    assert child["PLAYWRIGHT_BROWSERS_PATH"] == browsers
    assert "POLARIS_VIDEO_SCRIPT_API_KEY" not in child


def test_readonly_original_tree_stays_unchanged_but_task_copies_can_be_edited(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    code = """
import os,shutil,stat,sys
from pathlib import Path
from PIL import ImageFont
from app.video_editing_native_compat import install
root=Path(sys.argv[1]);package=root/'original';task=root/'task'
package.mkdir();task.mkdir()
source=package/'font.ttf';source.write_bytes(b'original-byte-identity')
source.chmod(stat.S_IRUSR|stat.S_IRGRP|stat.S_IROTH)
ImageFont.truetype=lambda *args: object()
install(package,task)
font=package/'assets'/'fonts'/'unicode-font.otf'
if os.name=='nt':
    loaded=ImageFont.truetype(font,36)
    assert ImageFont.truetype(font,36) is loaded
    assert ImageFont.truetype(font,37) is not loaded
    assert ImageFont.truetype(source,36) is not ImageFont.truetype(source,36)
shutil.copy2(source,task/'font.ttf')
shutil.copy2(source,task/'font.ttf')
shutil.copytree(package,task/'copied-tree')
(task/'copied-tree/font.ttf').write_bytes(b'new-task-data')
assert source.read_bytes()==b'original-byte-identity'
assert not source.stat().st_mode & stat.S_IWUSR
assert (task/'font.ttf').read_bytes()==source.read_bytes()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "task/compatibility").glob("copies-*.json"))


def test_worker_mattes_are_isolated_per_prepared_job(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    package = tmp_path / "package"
    module = package / "commercial_runtime/paths.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from pathlib import Path\n"
        "def cache_path(base, name='cache'):\n"
        "    return Path(base) / name\n",
        encoding="utf-8",
    )
    plans = tmp_path / "task/plans"
    plans.mkdir(parents=True)
    first, second, unrelated = (
        plans / f"{key}.json" for key in ("first", "next", "other")
    )
    first.write_text('{"group_id":"AZL01","offset":1}', encoding="utf-8")
    second.write_text('{"group_id":"AZL01","offset":2}', encoding="utf-8")
    unrelated.write_text('{"group_id":"CXBR02","offset":2}', encoding="utf-8")
    code = """
import sys
from pathlib import Path
from app.video_editing_native_compat import isolate_native_matte_cache
package, task = map(Path, sys.argv[1:3])
sys.path.insert(0, str(package))
isolate_native_matte_cache(package, task)
from commercial_runtime.paths import cache_path
print(cache_path('shared', 'cache/mattes').as_posix())
assert cache_path('shared', 'unrelated').as_posix() == 'shared/unrelated'
"""

    def cache_for(job):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                code,
                str(package),
                str(plans.parent),
                "--job",
                str(job),
            ],
            env={**os.environ, "PYTHONPATH": str(backend)},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip()

    first_cache = cache_for(first)
    assert first_cache != cache_for(second)
    first.write_text('{"group_id":"AZL01","offset":3}', encoding="utf-8")
    assert cache_for(first) != first_cache
    for group in ("YYO02", "YYO07", "YY6O04"):
        first.write_text(f'{{"group_id":"{group}","offset":1}}', encoding="utf-8")
        opening_cache = cache_for(first)
        first.write_text(f'{{"group_id":"{group}","offset":2}}', encoding="utf-8")
        assert cache_for(first) != opening_cache
    assert cache_for(unrelated) == "shared/cache/mattes"


def test_opening_shared_validator_receives_style_only_during_validation(
    tmp_path, monkeypatch
):
    package = tmp_path / "package"
    root = tmp_path / "task"
    entry = package / compat._LYO_SHARED_ENTRY
    loader = package / "commercial_runtime/native.py"
    template = package / compat._LYO_CIRCLE_INPUT
    for path in (entry, loader):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# validator scope fixture\n", encoding="utf-8")
    style = {"background": {"mode": "solid"}, "geometry": {}}
    atomic_json(template, {"style": style})
    job = root / "plans/opening.json"
    atomic_json(job, {"group_id": "LYO01"})
    monkeypatch.setattr(sys, "argv", ["worker", "--job", str(job)])
    monkeypatch.setattr(compat, "_LYO_CIRCLE_INPUT_SHA", sha256(template))
    monkeypatch.setattr(
        compat,
        "clock_profile",
        lambda _: {
            "source_files": {
                path.relative_to(package).as_posix(): sha256(path)
                for path in (entry, loader)
            }
        },
    )

    def original_validate(config):
        if config["content"] != {"caption": "本期词点"}:
            raise ValueError("Original text role validation")
        return config["style"]

    def original_draw(config):
        return set(config)

    def original_module(path, name):
        return SimpleNamespace(validate=original_validate, draw=original_draw)

    native = SimpleNamespace(__file__=str(loader), module=original_module)
    monkeypatch.setattr(compat.importlib, "import_module", lambda _: native)
    compat.install_native_opening_validator(package, root)
    config = {"group_id": "LYO01", "content": {"caption": "本期词点"}}
    loaded = native.module(entry)
    assert loaded.validate(config) == style
    assert "style" not in loaded.draw(config)
    with pytest.raises(ValueError, match="Original text role validation"):
        loaded.validate({**config, "content": {"unknown": "本期词点"}})
    assert native.module(loader).validate is original_validate
