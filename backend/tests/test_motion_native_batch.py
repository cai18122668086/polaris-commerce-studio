"""Protocol and alpha-evidence guard tests; no rendered user sample is faked."""

import pytest
from PIL import Image

from app.motion_library import MOTION_SHA256, atomic_json, sha256
from app.motion_native_batch import validate_manifest, verify_rgba_sequence


def test_batch_cannot_drop_or_double_count_an_original_group(tmp_path):
    atomic_json(
        tmp_path / "catalog/groups.json",
        {
            "groups": [
                {"id": "S1", "backend": "subtitle"},
                {"id": "S2", "backend": "subtitle"},
                {"id": "V1", "backend": "scene"},
            ]
        },
    )
    ready = {
        "group_id": "S1",
        "disposition": "ready",
        "beat": {"group_id": "S1"},
        "recipe": {"group_id": "S1"},
    }
    missing = {
        "group_id": "S2",
        "disposition": "blocked",
        "reason": "fixture font unbound",
        "blockers": [{"code": "EXACT_ORIGINAL_FONT_UNBOUND"}],
    }
    batch = {
        "version": "tengli.native-validation-batch/1",
        "library_release": MOTION_SHA256,
        "backend": "subtitle",
        "cases": [ready, missing],
    }
    assert validate_manifest(batch, tmp_path) == [ready, missing]
    for cases in (
        [ready],
        [ready, ready, missing],
        [ready, {**missing, "blockers": []}],
        [missing, {**ready, "recipe": {"group_id": "V1"}}],
    ):
        with pytest.raises(ValueError):
            validate_manifest({**batch, "cases": cases}, tmp_path)


def test_native_alpha_guard_rejects_blank_corrupt_and_foreign_frames(tmp_path):
    root = tmp_path / "instance"
    folder = root / "rgba"
    folder.mkdir(parents=True)
    first, second = folder / "0.png", folder / "1.png"
    frame = Image.new("RGBA", (8, 8))
    frame.save(first)
    frame.putpixel((4, 4), (255, 255, 255, 255))
    frame.save(second)
    report = {"rgba_sequence": str(folder)}

    def write(a, b):
        atomic_json(
            folder / "sequence.json", {"width": 8, "height": 8, "frames": [a, b]}
        )

    rows = [
        {"path": path.name, "frame": i, "sha256": sha256(path)}
        for i, path in enumerate((first, second))
    ]
    write(*rows)
    assert verify_rgba_sequence(root, report, 2)["visible_frames"] == 1
    write(rows[0], {**rows[0], "frame": 1})
    with pytest.raises(ValueError, match="no visible motion"):
        verify_rgba_sequence(root, report, 2)
    write(rows[0], {**rows[1], "sha256": "0" * 64})
    with pytest.raises(ValueError, match="missing or changed"):
        verify_rgba_sequence(root, report, 2)
    write(rows[0], {**rows[1], "path": "../../not-in-instance.png"})
    with pytest.raises(ValueError, match="missing or changed"):
        verify_rgba_sequence(root, report, 2)
