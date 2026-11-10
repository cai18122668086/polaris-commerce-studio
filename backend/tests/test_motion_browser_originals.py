import pytest
from PIL import Image

from app import motion_browser_originals as browser_originals
from app.motion_browser_originals import (
    BrowserOriginalsMissing,
    compile_browser_originals,
    intake_browser_originals,
    original_startup_assets,
    require_browser_originals,
)
from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256


@pytest.mark.parametrize(
    ("group_id", "presenter", "missing"),
    [
        ("CX-G05", "current", {"g05-assets/base-{i:03d}.jpg": 69}),
        (
            "CX-G05",
            "",
            {"g05-assets/base-{i:03d}.jpg": 69, "g05-assets/actor-{i:03d}.png": 69},
        ),
        ("CX-G08", "", {"legacy/assets/img/person.png": 1}),
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


def test_g05_checks_only_the_original_photo_for_the_unbound_item(tmp_path):
    atomic_json(tmp_path / "integrity.json", {"files": {}})
    with pytest.raises(BrowserOriginalsMissing) as caught:
        require_browser_originals(
            tmp_path,
            {"id": "CX-G05", "browser_directory": "engine"},
            {
                "presenter": "current",
                "items": [{"image": "current-a"}, {}, {"image": "current-c"}],
            },
        )
    assert caught.value.missing == {
        "g05-assets/base-{i:03d}.jpg": 69,
        "g05-assets/photo-{i}.jpg": 1,
    }


@pytest.mark.parametrize("group_id", ["CX-G04", "CX-G06", "CX-G08", "CX-G10"])
def test_unused_shared_startup_images_do_not_block_other_branches(tmp_path, group_id):
    group = {"id": group_id}
    config = {"presenter": "current"}
    manifest = tmp_path / "unrelated.json"
    manifest.write_text("unneeded", encoding="utf-8")
    assert require_browser_originals(tmp_path, group, config) == {}
    assert (
        compile_browser_originals(
            tmp_path, group, config, manifest, tmp_path / "browser-originals"
        )
        == {}
    )


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


@pytest.mark.parametrize("indexed", [False, True])
def test_supplement_freezes_bytes_and_checks_indexed_originals(tmp_path, indexed):
    package = tmp_path / "library"
    group = {"id": "CX-G09", "browser_directory": "engine"}
    config = {"presenter": "current"}
    stage = tmp_path / "attempt/browser-originals"
    manifest = tmp_path / "private-bindings.json"
    atomic_json(package / "integrity.json", {"files": {}})
    files = {}
    for i in range(3):
        file = tmp_path / f"original-{i}.png"
        Image.new("RGBA", (8, 8), (i * 90, 20, 40, 255)).save(file)
        files[f"engine/assets/material-{i}.png"] = {
            "path": str(file),
            "sha256": sha256(file),
            "original_source": "technical fixture",
            "use_scope": "original_delivery",
        }
    alias = "engine/assets/material-1.png"
    identity = {
        "id": "media-example",
        "kind": "media",
        "bytes": (tmp_path / "original-1.png").stat().st_size,
        "sha256": files[alias]["sha256"],
    }
    atomic_json(
        package / "catalog/native-relative-assets.json",
        {alias: "input://media-example"} if indexed else {},
    )
    external = package / "catalog/external-resources.json"
    atomic_json(external, {"resources": [identity] if indexed else []})
    if indexed:
        # A legacy registration with exact catalog bytes already has an identity.
        files[alias].pop("use_scope")
    atomic_json(
        manifest,
        {
            "browser_startup_originals": {
                "library_release": MOTION_SHA256,
                "files": files,
            }
        },
    )

    frozen = compile_browser_originals(package, group, config, manifest, stage)
    assert set(frozen) == files.keys()
    assert frozen[alias]["identity"] == (
        "catalog_sha256" if indexed else "operator_attested"
    )
    assert frozen[alias]["path"] == str(stage / f"{identity['sha256']}.png")
    material, backgrounds, *_ = original_startup_assets(package, group, manifest)
    assert material["verified_supplement_count"] == 3
    assert not material["missing_paths"]
    assert material["usage"] == "drawn"
    assert backgrounds["usage"] == "without_presenter"
    assert len(backgrounds["missing_paths"]) == 66
    (tmp_path / "original-1.png").write_bytes(b"registration source moved")
    material = original_startup_assets(package, group, manifest)[0]
    assert material["verified_supplement_count"] == 2
    assert material["missing_paths"] == [alias]
    assert str(tmp_path) not in str(material)
    assert require_browser_originals(package, group, config, frozen, stage) == frozen
    with pytest.raises(BrowserOriginalsMissing):
        require_browser_originals(package, group, config, files, stage)

    if indexed:
        atomic_json(external, {"resources": [{**identity, "sha256": "0" * 64}]})
        with pytest.raises(BrowserOriginalsMissing) as caught:
            require_browser_originals(package, group, config, frozen, stage)
        assert caught.value.missing == {"assets/material-{i}.png": 1}
    else:
        frozen_file = stage / f"{identity['sha256']}.png"
        frozen_file.write_bytes(b"mutated")
        with pytest.raises(BrowserOriginalsMissing) as caught:
            require_browser_originals(package, group, config, frozen, stage)
        assert caught.value.missing == {"assets/material-{i}.png": 1}


def test_diagnostic_and_unclassified_images_do_not_pass_original_checks(tmp_path):
    package, manifest = tmp_path / "package", tmp_path / "bindings.json"
    stage = tmp_path / "task/browser-originals"
    group = {"id": "CX-G05", "browser_directory": "engine"}
    config = {"presenter": "current"}
    original = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), "blue").save(original)
    digest = sha256(original)
    atomic_json(package / "integrity.json", {"files": {}})
    atomic_json(package / "catalog/native-relative-assets.json", {})
    atomic_json(package / "catalog/external-resources.json", {"resources": []})
    row = {"path": str(original), "sha256": digest, "original_source": "local test"}
    files = {
        f"engine/g05-assets/base-{index:03d}.jpg": row.copy() for index in range(69)
    }
    registry = {"library_release": MOTION_SHA256, "files": files}
    atomic_json(manifest, {"browser_startup_originals": registry})
    with pytest.raises(BrowserOriginalsMissing):
        compile_browser_originals(package, group, config, manifest, stage)
    for value in files.values():
        value["use_scope"] = "diagnostic"
    atomic_json(manifest, {"browser_startup_originals": registry})
    detail = original_startup_assets(package, group, manifest)[0]
    assert detail["verified_supplement_count"] == 0
    assert set(detail["missing_paths"]) == files.keys()
    with pytest.raises(BrowserOriginalsMissing):
        compile_browser_originals(package, group, config, manifest, stage)
    diagnostic = compile_browser_originals(
        package, group, config, manifest, stage, allow_diagnostic=True
    )
    assert diagnostic.keys() == files.keys()
    assert all(row["identity"] == "diagnostic" for row in diagnostic.values())
    with pytest.raises(BrowserOriginalsMissing):
        require_browser_originals(package, group, config, diagnostic, stage)
    assert (
        require_browser_originals(
            package, group, config, diagnostic, stage, allow_diagnostic=True
        )
        == diagnostic
    )


def test_intake_preserves_private_bindings_and_rejects_wrong_indexed_bytes(
    tmp_path, monkeypatch
):
    package, source = tmp_path / "package", tmp_path / "delivery"
    groups = [
        {"id": group_id, "browser_directory": "shared"}
        for group_id in ("CX-G08", "CX-G09", "CX-G10")
    ]
    atomic_json(package / "catalog/groups.json", {"groups": groups})
    atomic_json(package / "integrity.json", {"files": {}})
    monkeypatch.setattr(browser_originals, "verify_package", lambda _: None)
    folder = source / "shared/assets"
    folder.mkdir(parents=True)
    first = folder / "material-0.png"
    indexed = folder / "G10-background-clean.jpg"
    Image.new("RGB", (8, 8), "blue").save(first)
    Image.new("RGB", (8, 8), "green").save(indexed)
    key = indexed.relative_to(source).as_posix()
    identity = {
        "id": "media-original",
        "kind": "media",
        "bytes": indexed.stat().st_size,
        "sha256": sha256(indexed),
    }
    atomic_json(package / "catalog/external-resources.json", {"resources": [identity]})
    atomic_json(
        package / "catalog/native-relative-assets.json", {key: "input://media-original"}
    )
    exact = indexed.read_bytes()
    Image.new("RGB", (8, 8), "red").save(indexed)
    manifest = tmp_path / "bindings.json"
    previous = {"tools": {"ffmpeg": "private"}, "resources": {"font-a": "private"}}
    atomic_json(manifest, previous)
    initial_sha = sha256(manifest)
    options = {"source": source, "origin": "delivery provenance"}
    with pytest.raises(ValueError, match="Classify the delivery"):
        intake_browser_originals(package, manifest, **options)
    options["scope"] = "original_delivery"
    preview = intake_browser_originals(package, manifest, **options)
    assert preview["counts"] == {
        "ready_to_register": 1,
        "missing": 70,
        "rejected_candidate": 1,
    }
    rejected = next(row for row in preview["files"] if row["native_path"] == key)
    assert rejected["groups"] == ["CX-G08", "CX-G09", "CX-G10"]
    assert rejected["catalog_identity"]["sha256"] == identity["sha256"]
    assert sha256(manifest) == initial_sha
    assert str(source) not in str(preview) and options["origin"] not in str(preview)

    intake_browser_originals(
        package, manifest, **{**options, "scope": "diagnostic"}, apply=True
    )
    data = read_json(manifest)
    assert {k: data[k] for k in previous} == previous
    first_key = first.relative_to(source).as_posix()
    assert set(data["browser_startup_originals"]["files"]) == {first_key}
    registered = intake_browser_originals(package, manifest)
    assert registered["counts"]["diagnostic_registered"] == 1
    mistaken = intake_browser_originals(package, manifest, **options, apply=True)
    assert mistaken["counts"]["rejected_diagnostic_candidate"] == 1
    assert read_json(manifest) == data
    relocated = tmp_path / "relocated" / first.relative_to(source)
    relocated.parent.mkdir(parents=True)
    first.rename(relocated)
    mistaken = intake_browser_originals(
        package, manifest, **{**options, "source": tmp_path / "relocated"}, apply=True
    )
    assert mistaken["counts"]["rejected_diagnostic_candidate"] == 1
    assert read_json(manifest) == data
    Image.new("RGB", (8, 8), "yellow").save(first)
    indexed.write_bytes(exact)
    report = intake_browser_originals(package, manifest, **options, apply=True)
    assert report["counts"]["registered"] == 2
    indexed_row = next(row for row in report["files"] if row["native_path"] == key)
    assert indexed_row["identity"] == "catalog_sha256"
    registered = intake_browser_originals(package, manifest)
    assert registered["counts"]["verified_registered"] == 2
    locked = manifest.with_name(manifest.name + ".browser-intake.lock")
    locked.touch()
    Image.new("RGB", (8, 8), "red").save(folder / "material-1.png")
    with pytest.raises(FileExistsError):
        intake_browser_originals(package, manifest, **options, apply=True)
    assert set(read_json(manifest)["browser_startup_originals"]["files"]) == {
        first_key,
        key,
    }
