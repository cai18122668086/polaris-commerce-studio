import pytest

from app.motion_browser_originals import (
    BrowserOriginalsMissing,
    require_browser_originals,
)
from app.motion_library import atomic_json, sha256


@pytest.mark.parametrize(
    ("group_id", "presenter", "missing"),
    [
        ("CX-G05", "current", {"g05-assets/base-{i:03d}.jpg": 69}),
        (
            "CX-G05",
            "",
            {"g05-assets/base-{i:03d}.jpg": 69, "g05-assets/actor-{i:03d}.png": 69},
        ),
        ("CX-G09", "current", {"assets/material-{i}.png": 3}),
        ("CX-G09", "", {"assets/material-{i}.png": 3, "assets/g09-bg/{i:03d}.jpg": 66}),
        (
            "CX-G10",
            "",
            {"assets/G10-background-clean.jpg": 1, "assets/G10-person-clean.png": 1},
        ),
    ],
)
def test_only_images_drawn_in_the_current_branch_are_required(
    tmp_path, group_id, presenter, missing
):
    atomic_json(tmp_path / "integrity.json", {"files": {}})
    with pytest.raises(BrowserOriginalsMissing) as caught:
        require_browser_originals(
            tmp_path,
            {"id": group_id, "browser_directory": "engine"},
            {"presenter": presenter},
        )
    assert caught.value.missing == missing


@pytest.mark.parametrize("group_id", ["CX-G04", "CX-G06", "CX-G08", "CX-G10"])
def test_unused_shared_startup_images_do_not_block_other_branches(tmp_path, group_id):
    require_browser_originals(tmp_path, {"id": group_id}, {"presenter": "current"})


def test_missing_or_changed_original_bytes_cannot_be_supplied_by_an_unindexed_file(
    tmp_path,
):
    group = {"id": "CX-G09", "browser_directory": "engine"}
    directory = tmp_path / "engine/assets"
    directory.mkdir(parents=True)
    files = {}
    for i in range(3):
        image = directory / f"material-{i}.png"
        image.write_bytes(f"archive image {i}".encode())
        files[image.relative_to(tmp_path).as_posix()] = sha256(image)
    manifest = tmp_path / "integrity.json"
    atomic_json(manifest, {"files": files})
    require_browser_originals(tmp_path, group, {"presenter": "current"})

    (directory / "material-1.png").write_bytes(b"different")
    files.pop("engine/assets/material-2.png")
    atomic_json(manifest, {"files": files})
    with pytest.raises(BrowserOriginalsMissing) as caught:
        require_browser_originals(tmp_path, group, {"presenter": "current"})
    assert caught.value.missing == {"assets/material-{i}.png": 2}
