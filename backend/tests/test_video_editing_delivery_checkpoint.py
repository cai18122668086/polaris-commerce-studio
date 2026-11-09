from pathlib import Path

from app.motion_library import atomic_json
from app.video_editing_delivery_checkpoint import (
    checkpoint_for,
    compiled_digest,
    delivery_file,
    restore_delivery,
)


def test_compiled_identity_changes_with_native_input_or_request(tmp_path: Path) -> None:
    first, second = tmp_path / "aabbccdd", tmp_path / "aabbddee"
    for root in (first, second):
        atomic_json(
            root / "episode.json",
            {
                "instance_dir": str(root),
                "source": (root / "input/source.mp4").as_posix(),
            },
        )
        for name in ("bindings.json", "selection.json", "transcript.json"):
            atomic_json(root / name, {})
    digest = compiled_digest(first, "same-request")
    assert compiled_digest(second, "same-request") == digest
    assert compiled_digest(second, "another-request") != digest
    atomic_json(second / "selection.json", {"shots": ["SG-S09"]})
    assert compiled_digest(second, "same-request") != digest


def test_delivery_reuses_only_intact_artifacts_of_the_current_task(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    first, second = root / "aabbccdd", root / "aabbddee"
    master, proxy = first / "outputs/episode.mp4", second / "outputs/preview.mp4"
    for path in (master, proxy):
        path.parent.mkdir(parents=True)
        path.write_bytes(path.name.encode())
    files = {"staged_final": delivery_file(master), "preview": delivery_file(proxy)}
    validation = {
        "decoded": True,
        "duration_ms": 1000,
        "native_source_sha256": "source",
        "sha256": files["staged_final"].sha256,
    }
    proxy_validation = {
        "decoded": True,
        "duration_ms": 1000,
        "native_render_sha256": validation["sha256"],
        "sha256": files["preview"].sha256,
    }
    for role, name, payload in (
        ("receipt", "validation.json", validation),
        ("transcript", "transcript.json", {}),
        ("caption_anchors", "caption-anchors.json", {}),
        ("caption_receipt", "caption-segmentation.json", {}),
        ("caption_layout", "caption-adapter-layout.json", {}),
        ("preview_receipt", "preview-validation.json", proxy_validation),
    ):
        path = (second if role == "preview_receipt" else first) / name
        atomic_json(path, payload)
        files[role] = delivery_file(path)
    checkpoint = checkpoint_for(root, "compiled", files)

    def restore():
        return restore_delivery(
            checkpoint, root, "compiled", "source", "staged_final", set(), lambda: None
        )

    assert restore() == (
        files,
        {"staged_final": validation, "preview": proxy_validation},
    )
    proxy.write_bytes(b"X" * proxy.stat().st_size)
    restored = restore()
    assert restored is not None
    assert set(restored[0]) == files.keys() - {"preview", "preview_receipt"}
    assert restored[1] == {"staged_final": validation}
    checkpoint["files"]["caption_anchors"]["path"] = "../caption-anchors.json"
    assert restore() is None
    checkpoint["files"]["caption_anchors"]["path"] = "aabbccdd/caption-anchors.json"
    master.write_bytes(b"X" * master.stat().st_size)
    assert restore() is None
