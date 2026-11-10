import pytest

from app import video_editing_browser_boot as boot
from app.motion_library import atomic_json, sha256


def test_browser_boot_fonts_use_exact_bound_bytes_and_original_aliases(
    tmp_path, monkeypatch
):
    package = tmp_path / "library"
    group = {"id": "CX-G08", "entry": "entry/engine.js", "browser_directory": "entry"}
    for key, relative in (
        ("_ENGINE", group["entry"]),
        ("_LEGACY", "entry/legacy/src/renderer.html"),
        ("SPLIT_WRAPPER_SHA", "commercial_runtime/special.py"),
    ):
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relative, encoding="utf-8")
        monkeypatch.setattr(boot, key, sha256(target))
    bundled = package / boot._BUNDLED_FONT
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"bundled font identity fixture")
    atomic_json(
        package / "integrity.json", {"files": {boot._BUNDLED_FONT: sha256(bundled)}}
    )
    aliases = {
        f"entry/{relative}": "input://" + rid
        for relative, rid in boot._FONT_ALIASES.items()
    }
    aliases[f"entry/{boot._BUNDLED_ALIAS}"] = "pkg://" + boot._BUNDLED_FONT
    atomic_json(package / "catalog/native-relative-assets.json", aliases)
    resources, identities = {}, []
    for rid in boot.BROWSER_BOOT_FONT_IDS:
        candidate = tmp_path / f"{rid}.ttf"
        candidate.write_bytes(rid.encode())
        resources[rid] = str(candidate)
        identities.append(
            {
                "id": rid,
                "kind": "font",
                "sha256": sha256(candidate),
                "bytes": candidate.stat().st_size,
            }
        )
    atomic_json(package / "catalog/external-resources.json", {"resources": identities})

    missing, mismatch, *_ = boot.BROWSER_BOOT_FONT_IDS
    incomplete = resources.copy()
    incomplete.pop(missing)
    incomplete[mismatch] = resources[missing]
    with pytest.raises(boot.BrowserBootFontsMissing) as caught:
        boot.require_browser_boot_fonts(package, group, incomplete)
    assert caught.value.states == {
        missing: "not_registered",
        mismatch: "identity_mismatch",
    }
    assert str(tmp_path) not in str(caught.value)
    assert boot.require_browser_boot_fonts(package, group, resources) == resources

    override = package / "entry/assets/zhixiang.ttf"
    override.parent.mkdir()
    override.write_bytes(b"local override")
    with pytest.raises(ValueError, match="alias changed or was overridden"):
        boot.require_browser_boot_fonts(package, group, resources)
