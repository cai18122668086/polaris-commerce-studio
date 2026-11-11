from pathlib import Path

import pytest

from app.motion_library import MOTION_SHA256, atomic_json, read_json, sha256
from app.motion_local_dependencies import (
    NONCOMMERCIAL_FONT,
    component_use_state,
    font_use_state,
    intake_local_dependencies,
    local_dependencies,
    resolve_local_binding,
)
from app.video_editing_hypit_label_cards import (
    LABEL_CARD_FONT,
    require_label_card_font,
)


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


def test_restricted_font_bytes_and_component_reference_are_separate(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.motion_local_dependencies.verify_package", lambda _: None)
    package, registry, task = (
        tmp_path / name for name in ("package", "registry.json", "task.json")
    )
    font = tmp_path / "font.ttf"
    font.write_bytes(b"original identity fixture")
    identity = {
        "id": LABEL_CARD_FONT,
        "kind": "font",
        "bytes": font.stat().st_size,
        "sha256": sha256(font),
        "rights": NONCOMMERCIAL_FONT,
    }
    atomic_json(package / "catalog/external-resources.json", {"resources": [identity]})
    paths = {LABEL_CARD_FONT: str(font)}
    atomic_json(task, {"resources": paths})
    config = {"fonts": {"junya": "input://" + LABEL_CARD_FONT}}
    candidates = {LABEL_CARD_FONT: font}
    options = {"origin": "original-delivery", "apply": True}
    recorded = intake_local_dependencies(package, registry, candidates, **options)
    assert recorded["resources"][0]["candidate"] == "verified"
    assert recorded["resources"][0]["component_use_state"] == "reference_required"
    with pytest.raises(ValueError, match="component use reference"):
        require_label_card_font(package, config, task, registry)

    reference = "private-component-approval-1"
    supplied = intake_local_dependencies(
        package,
        registry,
        candidates,
        component_references={LABEL_CARD_FONT: reference},
        **options,
    )
    assert supplied["manifest_updated"]
    assert supplied["resources"][0]["retains_verified_binding"]
    assert supplied["resources"][0]["component_use_state"] == "reference_recorded"
    assert reference not in str(supplied)
    assert local_dependencies(registry) == paths
    require_label_card_font(package, config, task, registry)
    assert font_use_state(identity, registry, "episode") == "reference_required"
    with pytest.raises(ValueError, match="episode use reference"):
        require_label_card_font(package, config, task, registry, scope="episode")
    episode_reference = "private-episode-approval-fixture"
    granted = intake_local_dependencies(
        package,
        registry,
        candidates,
        episode_references={LABEL_CARD_FONT: episode_reference},
        **options,
    )
    assert granted["resources"][0]["episode_use_state"] == "reference_recorded"
    assert episode_reference not in str(granted)
    assert component_use_state(identity, registry) == "reference_recorded"
    require_label_card_font(package, config, task, registry, scope="episode")
    with pytest.raises(ValueError, match="original Junya font slot"):
        require_label_card_font(package, {"fonts": {}}, task, registry)
    assert not intake_local_dependencies(package, registry, candidates, **options)[
        "manifest_updated"
    ]

    document = read_json(registry)
    receipt = document["resource_intake"][LABEL_CARD_FONT]
    receipt["sha256"] = "0" * 64
    atomic_json(registry, document)
    assert component_use_state(identity, registry) == "reference_required"
    with pytest.raises(ValueError, match="component use reference"):
        require_label_card_font(package, config, task, registry)
    receipt["sha256"] = identity["sha256"]
    atomic_json(registry, document)
    font.write_bytes(b"different font contents")
    with pytest.raises(ValueError, match="exact original font bytes"):
        require_label_card_font(package, config, task, registry)


def test_portable_intake_relocates_exact_bytes_and_keeps_legacy_entries(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.motion_local_dependencies.verify_package", lambda _: None)
    package, bundle, destination = (
        tmp_path / name for name in ("package", "portable", "relocated")
    )
    font = bundle / "fonts" / "received.ttf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"original")
    manifest = bundle / "bindings.json"
    unrelated = tmp_path / "legacy.ttf"
    unrelated.write_bytes(font.read_bytes())
    atomic_json(
        manifest, {"resources": {"original": str(unrelated), "legacy": str(unrelated)}}
    )
    atomic_json(
        package / "catalog/external-resources.json",
        {"resources": [{"id": "original", "kind": "font", "sha256": sha256(font)}]},
    )
    with pytest.raises(ValueError, match="under the bindings directory"):
        intake_local_dependencies(
            package, manifest, {"original": unrelated}, portable=True
        )
    options = {"apply": True, "origin": "original-delivery", "portable": True}
    assert intake_local_dependencies(package, manifest, {"original": font}, **options)[
        "manifest_updated"
    ]
    assert not intake_local_dependencies(
        package, manifest, {"original": font}, **options
    )["manifest_updated"]
    assert (
        read_json(manifest)["resources"]["original"] == "registry://fonts/received.ttf"
    )
    bundle.rename(destination)
    moved = destination / manifest.name
    bindings = local_dependencies(moved)
    assert Path(bindings["original"]) == destination / "fonts" / font.name
    assert sha256(Path(bindings["original"])) == sha256(unrelated)
    assert Path(bindings["legacy"]) == unrelated
    for invalid in (
        "../legacy.ttf",
        "registry://../legacy.ttf",
        "registry://fonts/../../legacy.ttf",
        "registry:///legacy.ttf",
        "registry://C:/legacy.ttf",
        "registry://fonts\\..\\legacy.ttf",
    ):
        assert resolve_local_binding(moved, invalid) is None
    try:
        (destination / "link.ttf").symlink_to(unrelated)
    except OSError:
        return
    assert resolve_local_binding(moved, "registry://link.ttf") is None
