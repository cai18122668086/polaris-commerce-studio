from pathlib import Path

import pytest

from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_native_shot_recovery import (
    _matches_shot_clock,
    _request_sha,
    _restore_shot,
    _seal,
    _verify_hypit_encoding,
)


def test_native_shot_clock_must_fit_episode() -> None:
    receipt = {"encoding": {"format": {"frames": 90, "fps": 30}}}
    assert _matches_shot_clock(receipt, 3.015, 30)
    assert not _matches_shot_clock(receipt, 3.1, 30)
    assert not _matches_shot_clock({}, 3, 30)


def test_hypit_receipt_requires_measured_clock_and_strict_decode(tmp_path, monkeypatch):
    output = tmp_path / "original-hypit.mp4"
    output.write_bytes(b"fixture shot")
    receipt = {"decoded": True, "build_id": "native-build", "sha256": sha256(output)}
    monkeypatch.setattr(
        "app.video_editing_native_shot_recovery.subprocess.check_output",
        lambda *args, **kwargs: (
            b'{"streams":[{"nb_read_frames":"120","avg_frame_rate":"30/1",'
            b'"width":1080,"height":1920}]}'
        ),
    )
    decode_calls = []
    monkeypatch.setattr(
        "app.video_editing_native_shot_recovery.subprocess.run",
        lambda argv, **kwargs: decode_calls.append((argv, kwargs)),
    )
    path = output.with_suffix(".receipt.json")
    with pytest.raises(ValueError, match="frame clock"):
        _verify_hypit_encoding(output, receipt, 5, 30)
    assert not path.exists() and not decode_calls
    verified = _verify_hypit_encoding(output, receipt, 4, 30)
    assert verified["build_id"] == "native-build"
    assert verified["encoding"]["format"]["frames"] == 120
    assert verified["encoding"]["full_decode"] is True
    assert read_json(path) == verified
    assert "-xerror" in decode_calls[0][0] and decode_calls[0][1]["check"]


def test_native_shot_requires_same_prepared_job_and_complete_rgba(
    tmp_path: Path,
) -> None:
    previous = (tmp_path / "aabbccdd").resolve()
    current = (tmp_path / "aabbeecc").resolve()
    previous.mkdir()
    current.mkdir()

    def request(root: Path, text: str = "桌面") -> dict:
        return {
            "schema": "commercial-talk-job/1",
            "group_id": "SG-S09",
            "config": {"text": text, "source": str(root / "input/source.mp4")},
            "output": str(root / "renders/000-SG-S09.mp4"),
        }

    old_job = request(previous)
    old = Path(old_job["output"])
    sequence = old.with_name(old.stem + "-rgba")
    sequence.mkdir(parents=True)
    old.write_bytes(b"checkpoint test component bytes")
    frame = sequence / "000000.png"
    frame.write_bytes(b"checkpoint test frame bytes")
    atomic_json(
        sequence / "sequence.json",
        {"frames": [{"frame": 0, "path": frame.name, "sha256": sha256(frame)}]},
    )
    receipt = {
        "decoded": True,
        "group_id": old_job["group_id"],
        "encoding": {"full_decode": True, "output": str(old)},
        "native": {"frames": 1},
        "output": str(old),
        "library_sha256": "library",
        "public_request_sha256": _request_sha(old_job),
        "sha256": sha256(old),
        "rgba_sequence": str(sequence),
    }
    atomic_json(previous / "plans/000-SG-S09-native-input.json", old_job)
    atomic_json(old.with_suffix(".receipt.json"), receipt)
    _seal(previous, old, receipt, None)

    job = request(current)
    output = Path(job["output"])
    assert not _restore_shot(
        previous, current, output, request(current, "说明"), "library", True
    )
    assert not output.exists()
    original_frame = frame.read_bytes()
    frame.write_bytes(b"X" * len(original_frame))
    assert not _restore_shot(previous, current, output, job, "library", True)
    assert not output.exists()
    frame.write_bytes(original_frame)
    assert _restore_shot(previous, current, output, job, "library", True)
    restored = read_json(output.with_suffix(".receipt.json"))
    assert restored["output"] == restored["encoding"]["output"] == str(output)
    assert restored["public_request_sha256"] == _request_sha(job)
    assert restored["sha256"] == sha256(output) == sha256(old)
    assert (Path(restored["rgba_sequence"]) / frame.name).read_bytes() == original_frame
    assert read_json(old.with_suffix(".receipt.json")) == receipt
