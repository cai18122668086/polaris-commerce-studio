from pathlib import Path

import pytest

from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from app.motion_local_dependencies import intake_local_dependencies, local_dependencies


def test_intake_merges_exact_dependencies_without_erasing_other_registrations(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.motion_local_dependencies.verify_package", lambda _: None)
    package = tmp_path / "package"
    manifest = tmp_path / "bindings.json"
    font = tmp_path / "received.ttf"
    other = tmp_path / "another.ttf"
    font.write_bytes(b"font identity fixture")
    other.write_bytes(b"second font fixture")
    identities = [
        {
            "id": rid,
            "kind": "font",
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "rights": "not_reviewed_do_not_bundle",
        }
        for rid, path in (("font-a", font), ("font-b", other))
    ]
    atomic_json(package / "catalog/external-resources.json", {"resources": identities})
    previous = {
        "tools": {"ffmpeg": "existing tool"},
        "resources": {"model-existing": str(tmp_path / "model.onnx")},
        "browser_startup_originals": {"library_release": MOTION_SHA256, "files": {}},
    }
    atomic_json(manifest, previous)
    starting_sha = sha256(manifest)
    candidates = {"font-a": font, "font-b": other}
    preview = intake_local_dependencies(package, manifest, candidates)
    assert preview["ready"] and not preview["manifest_updated"]
    assert preview["resources"][0]["original_rights"] == "not_reviewed_do_not_bundle"
    assert str(tmp_path) not in str(preview)
    assert sha256(manifest) == starting_sha

    options = {"origin": "delivery-1", "apply": True}
    rejected = intake_local_dependencies(
        package, manifest, {"font-a": font, "font-b": font}, **options
    )
    assert not rejected["ready"] and not rejected["manifest_updated"]
    assert rejected["resources"][1]["candidate"] == "identity_mismatch"
    assert sha256(manifest) == starting_sha

    lock = manifest.with_name(manifest.name + ".browser-intake.lock")
    lock.touch()
    with pytest.raises(FileExistsError):
        intake_local_dependencies(package, manifest, candidates, **options)
    lock.unlink()

    applied = intake_local_dependencies(package, manifest, candidates, **options)
    assert applied["manifest_updated"]
    saved = read_json(manifest)
    assert saved["tools"] == previous["tools"]
    assert saved["browser_startup_originals"] == previous["browser_startup_originals"]
    assert {rid: Path(path) for rid, path in local_dependencies(manifest).items()} == {
        "model-existing": tmp_path / "model.onnx",
        **candidates,
    }
    assert saved["resource_intake"]["font-a"] == {
        "library_release": MOTION_SHA256,
        "sha256": identities[0]["sha256"],
        "delivery_reference": "delivery-1",
    }
    saved_sha = sha256(manifest)
    assert not intake_local_dependencies(package, manifest, candidates, **options)[
        "manifest_updated"
    ]
    assert sha256(manifest) == saved_sha
