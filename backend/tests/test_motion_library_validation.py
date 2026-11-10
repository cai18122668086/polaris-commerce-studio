import pytest

from app.config import Settings
from app.motion_library import MOTION_SHA256, atomic_json, sha256, verify_package
from app.motion_library_validation import (
    canonical_hash,
    group_status,
    motion_evidence_directory,
    record_failure,
    record_native,
)


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
    atomic_json(
        shared / MOTION_SHA256[:12] / "HY-A2/sample.json",
        {
            "release": MOTION_SHA256,
            "group_id": "HY-A2",
            "recorded_at": "2026-11-11T00:00:00+00:00",
            "runtime_validation": "sample_rendered",
        },
    )
    monkeypatch.setenv("POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR", str(shared))
    for tasks in (first, second):
        settings = Settings(_env_file=None, video_editing_tasks_dir=tasks)
        status = group_status(motion_evidence_directory(settings), "HY-A2")
        assert status["runtime_validation"] == "sample_rendered"
        assert status["visual_acceptance"] == "unreviewed"
    assert (
        group_status(motion_evidence_directory(original), "HY-A2")["runtime_validation"]
        == "unverified"
    )


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
        "encoding": {"full_decode": True, "frames_written": 1, "format": {"frames": 1}},
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
