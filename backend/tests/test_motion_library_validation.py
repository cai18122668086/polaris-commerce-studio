import pytest

from app.config import Settings
from app.motion_browser_originals import BROWSER_ORIGINALS_KEY, BrowserOriginalsMissing
from app.motion_library import MOTION_SHA256, atomic_json, sha256, verify_package
from app.motion_library_validation import (
    EVIDENCE_SCHEMA,
    canonical_hash,
    group_status,
    motion_evidence_directory,
    record_failure,
    record_native,
)


def encoded_record(group_id, evidence_id):
    return {
        "schema": EVIDENCE_SCHEMA,
        "release": MOTION_SHA256,
        "id": evidence_id,
        "group_id": group_id,
        "recorded_at": "2026-11-11T00:00:00+00:00",
        "runtime_validation": "sample_rendered",
        "input_sha256": "a" * 64,
        "receipt_sha256": "b" * 64,
        "output_sha256": "c" * 64,
        "format": {"fps": 30.0, "width": 720, "height": 1280, "frames": 120},
        "scope": "record shape fixture only",
        "visual_acceptance": "unreviewed",
        "semantic_review": "unreviewed",
        "listening_review": "unreviewed",
    }


def test_library_evidence_is_shared_across_task_volumes_when_configured(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR", raising=False)
    first, second = tmp_path / "first", tmp_path / "second"
    original = Settings(_env_file=None, video_editing_tasks_dir=first)
    assert motion_evidence_directory(original) == (
        first / "_library-validation" / MOTION_SHA256[:12]
    )
    shared = tmp_path / "library-evidence"
    evidence_id = "a" * 32
    atomic_json(
        shared / MOTION_SHA256[:12] / "HY-A2" / f"{evidence_id}.json",
        encoded_record("HY-A2", evidence_id),
    )
    monkeypatch.setenv("POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR", str(shared))
    for tasks in (first, second):
        settings = Settings(_env_file=None, video_editing_tasks_dir=tasks)
        status = group_status(motion_evidence_directory(settings), "HY-A2")
        assert status["runtime_validation"] == "sample_rendered"
        assert status["visual_acceptance"] == "unreviewed"
        assert status["runtime_evidence_rejected"] == 0
    assert (
        group_status(motion_evidence_directory(original), "HY-A2")["runtime_validation"]
        == "unverified"
    )


def test_transferred_evidence_rejects_incomplete_records_without_losing_valid_groups(
    tmp_path,
):
    valid = encoded_record("HY-A2", "a" * 32)
    atomic_json(tmp_path / "HY-A2" / f"{valid['id']}.json", valid)
    corrupt = tmp_path / "HY-A2" / ("b" * 32 + ".json")
    corrupt.write_bytes(b'{"schema":')
    incomplete = encoded_record("HY-A1", "c" * 32)
    incomplete.pop("output_sha256")
    atomic_json(tmp_path / "HY-A1" / f"{incomplete['id']}.json", incomplete)
    atomic_json(tmp_path / "HY-A1" / f"{valid['id']}.json", valid)

    a2 = group_status(tmp_path, "HY-A2")
    assert a2["runtime_evidence"] == [valid]
    assert a2["runtime_validation"] == "sample_rendered"
    assert a2["runtime_evidence_rejected"] == 1
    a1 = group_status(tmp_path, "HY-A1")
    assert a1["runtime_validation"] == "unverified"
    assert a1["runtime_evidence_rejected"] == 2
    assert corrupt.read_bytes() == b'{"schema":'


def test_browser_evidence_requires_active_originals_and_matching_receipt(
    tmp_path, monkeypatch
):
    package, instance, state = (tmp_path / n for n in ("package", "instance", "state"))
    group = {"id": "CX-G09", "backend": "browser", "browser_directory": "engine"}
    atomic_json(package / "catalog/groups.json", {"groups": [group]})
    integrity = package / "integrity.json"
    atomic_json(integrity, {"files": {}})
    monkeypatch.setattr("app.motion_library_validation.verify_package", lambda _: None)
    output = instance / "renders/new.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"test render receipt")
    job = {"group_id": group["id"], "config": {"presenter": "current"}}
    atomic_json(instance / "plans/new-native-input.json", job)
    report = {
        "group_id": group["id"],
        "output": str(output),
        "decoded": True,
        "sha256": sha256(output),
        "library_sha256": sha256(integrity),
        "public_request_sha256": canonical_hash(job),
        "native": {"frames": 1},
        "encoding": {
            "full_decode": True,
            "frames_written": 1,
            "format": {"fps": 30.0, "width": 720, "height": 1280, "frames": 1},
        },
    }
    receipt = instance / "report.json"
    atomic_json(receipt, report)
    with pytest.raises(BrowserOriginalsMissing):
        record_native(package, state, instance, receipt)
    asset_root = package / "engine/assets"
    asset_root.mkdir(parents=True)
    files = {}
    for i in range(3):
        asset = asset_root / f"material-{i}.png"
        asset.write_bytes(bytes([i]))
        files[asset.relative_to(package).as_posix()] = sha256(asset)
    atomic_json(integrity, {"files": files})
    report["library_sha256"] = sha256(integrity)
    report["native"][BROWSER_ORIGINALS_KEY] = {
        "unexpected": {"use_scope": "diagnostic"}
    }
    atomic_json(receipt, report)
    with pytest.raises(ValueError, match="lacks matching original browser images"):
        record_native(package, state, instance, receipt)
    del report["native"][BROWSER_ORIGINALS_KEY]
    atomic_json(receipt, report)
    saved = record_native(package, state, instance, receipt)
    assert saved["browser_originals_checked"] is True
    legacy_id = "a" * 32
    atomic_json(
        state / group["id"] / f"{legacy_id}.json",
        encoded_record(group["id"], legacy_id),
    )
    status = group_status(state, group["id"])
    assert status["runtime_evidence"] == [saved]
    assert status["runtime_evidence_rejected"] == 1


def test_installed_motion_cannot_supply_its_own_integrity_manifest(tmp_path):
    entry = tmp_path / "commercial_runtime/entry.py"
    entry.parent.mkdir()
    entry.write_bytes(b"unapproved replacement")
    atomic_json(
        tmp_path / "integrity.json",
        {
            "algorithm": "sha256",
            "files": {"commercial_runtime/entry.py": sha256(entry)},
        },
    )
    with pytest.raises(ValueError, match=r"metadata integrity failed: integrity\.json"):
        verify_package(tmp_path)


def test_native_evidence_cannot_promote_changed_bytes_or_human_acceptance(
    tmp_path, monkeypatch
):
    package, instance, state = (tmp_path / n for n in ("package", "instance", "state"))
    atomic_json(package / "catalog/groups.json", {"groups": [{"id": "G1"}]})
    atomic_json(package / "integrity.json", {})
    monkeypatch.setattr("app.motion_library_validation.verify_package", lambda _: None)
    output = instance / "renders/new.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"receipt-verification-fixture-not-a-render")
    job = {"group_id": "G1", "output": str(output)}
    atomic_json(instance / "plans/new-native-input.json", job)
    report = {
        "group_id": "G1",
        "output": str(output),
        "decoded": True,
        "sha256": sha256(output),
        "library_sha256": sha256(package / "integrity.json"),
        "public_request_sha256": canonical_hash(job),
        "native": {"frames": 1},
        "encoding": {
            "full_decode": True,
            "frames_written": 1,
            "format": {"fps": 30.0, "width": 720, "height": 1280, "frames": 1},
        },
        "visual_acceptance": "approved",
    }
    receipt = instance / "report.json"
    atomic_json(receipt, report)
    saved = record_native(package, state, instance, receipt)
    assert saved["visual_acceptance"] == "unreviewed"
    assert str(tmp_path) not in str(saved)
    assert group_status(state, "G1")["runtime_validation"] == "sample_rendered"
    output.write_bytes(b"changed")
    with pytest.raises(ValueError):
        record_native(package, state, instance, receipt)
    assert len(group_status(state, "G1")["runtime_evidence"]) == 1
    atomic_json(instance / "job.json", job)
    atomic_json(
        instance / "failure.json", {"status": "failed", "error": "RuntimeError"}
    )
    record_failure(package, state, instance, instance / "failure.json")
    assert group_status(state, "G1")["runtime_validation"] == "mixed_samples"
    assert group_status(state, "G2")["runtime_validation"] == "unverified"
