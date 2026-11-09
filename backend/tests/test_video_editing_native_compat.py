import os
import subprocess
import sys
from pathlib import Path


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
