import pytest

from app.motion_library import atomic_json, sha256
from app.motion_library_validation import (
    canonical_hash,
    group_status,
    record_failure,
    record_native,
)


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
