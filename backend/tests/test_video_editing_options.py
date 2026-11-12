"""Front-loaded choices retain provenance, replay identity, and render effects."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import video_editing_planning_preview as preview
from app import video_editing_worker as worker
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_contracts import (
    EditingOptions,
    EditingPlanningTaskCreate,
    Transcript,
    TranscriptToken,
)
from app.video_editing_task_models import EditingPlanningTaskRecord
from tests.test_video_editing_planning_tasks import setup
from tests.test_video_editing_tasks import setup_source
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def test_optional_fields_leave_historical_payloads_unchanged():
    assert "reference_script" not in EditingOptions().model_dump(mode="json")
    assert (
        "reference_script" not in EditingOptions(reference_script=" \n ").model_dump()
    )
    assert "music" not in EditingPlanningTaskCreate(request_id=uuid4()).model_dump()
    with pytest.raises(ValidationError):
        EditingOptions(reference_script="字" * 20001)
    with pytest.raises(ValidationError):
        EditingOptions(
            mode="native_plan", native_plan_id=uuid4(), reference_script="改稿"
        )
    with pytest.raises(ValidationError):
        EditingPlanningTaskCreate(
            request_id=uuid4(), mode="generate", prepared_task_id=uuid4(), music="off"
        )


def test_reference_is_task_scoped_and_changes_idempotent_input(video, tmp_path):
    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {"mode": "transcript", "reference_script": "  先上传产品图。 \n"},
    }
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["options"]["reference_script"] == "先上传产品图。"
    assert client.post(url, json=body).json()["id"] == first.json()["id"]
    body["options"]["reference_script"] = "再拉取参考商品。"
    assert client.post(url, json=body).status_code == 409
    body["request_id"] = str(uuid4())
    assert client.post(url, json=body).json()["id"] != first.json()["id"]
    assert first.json()["source_origin"].get("confirmed_version_id") is None


def test_user_reference_drives_recognition_but_preserves_confirmed_reference(
    tmp_path, monkeypatch
):
    from app.config import Settings

    settings = Settings(_env_file=None)
    old = tmp_path / "old.json"
    transcript = Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=1000,
        language="zh",
        provider=settings.video_editing_asr_provider,
        model=settings.video_editing_asr_model,
        tokens=[TranscriptToken(id="t0", text="实际口播", start_ms=0, end_ms=800)],
        utterances=[],
        reference_text="旧参考",
    )
    atomic_json(old, transcript.model_dump(mode="json"))
    snapshot = {
        "correction": None,
        "reference": "不可变确认稿",
        "options": {
            "mode": "transcript",
            "language": "zh",
            "reference_script": "新参考",
        },
        "checkpoint": {
            "transcript": {"profile": "旧参考", "path": str(old), "sha256": sha256(old)}
        },
    }
    captured = []
    monkeypatch.setattr(worker, "asr_profile", lambda _s, _l, reference: reference)

    def recognize(_command, folder, *_args):
        config = read_json(folder / "asr-config.json")
        captured.append(config["reference"])
        atomic_json(
            folder / "transcript.json",
            transcript.model_copy(
                update={"reference_text": config["reference"]}
            ).model_dump(mode="json"),
        )

    monkeypatch.setattr(worker, "run", recognize)
    root = tmp_path / "new"
    root.mkdir()
    checkpoints = []
    result = worker.load_transcript(
        "task",
        root,
        {"source_sha256": "a" * 64, "audio_sha256": "b" * 64, "duration_ms": 1000},
        snapshot,
        settings,
        lambda: None,
        lambda _stage, **details: checkpoints.append(details),
    )
    assert captured == ["新参考"]  # Old cached words were not reused.
    assert result.reference_text == "新参考"
    assert snapshot["reference"] == "不可变确认稿"
    assert checkpoints[-1]["transcript"]["profile"] == "新参考"


def test_music_preference_is_frozen_and_replay_cannot_change_it(
    video, tmp_path, monkeypatch
):
    client, _, ws, _, _, task, _ = setup(video, tmp_path, monkeypatch)
    url = base(ws) + f"/editing-tasks/{task['id']}/planning-tasks"
    body = {"request_id": str(uuid4()), "music": "off"}
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert client.post(url, json=body).json()["id"] == first.json()["id"]
    assert client.post(url, json={**body, "music": "lower"}).status_code == 409
    with client.app.state.session_factory() as session:
        saved = session.get(EditingPlanningTaskRecord, first.json()["id"])
        assert saved.snapshot["music"] == "off"


@pytest.mark.parametrize("choice", ["template", "off", "lower"])
@pytest.mark.parametrize("has_music", [True, False])
def test_automatic_and_manual_preview_apply_saved_music_or_noop(
    monkeypatch, choice, has_music
):
    candidate = SimpleNamespace(
        id=str(uuid4()),
        source_id=str(uuid4()),
        details={"source_subtitles": "none"},
        recipes={
            "design": {"caption_font_id": "font-d1961be1161ea1be"},
            "sound": {"music": ["track"] if has_music else []},
        },
    )
    row = SimpleNamespace(id=str(uuid4()), result={}, snapshot={"music": choice})
    monkeypatch.setattr(preview, "require_workspace_write", lambda _: None)
    monkeypatch.setattr(preview, "gateway_candidate", lambda *_: candidate)
    captured = []
    monkeypatch.setattr(
        preview,
        "persist_editing_task",
        lambda body, *_args, **_kw: captured.append(body) or (body, True),
    )
    preview.persist_planning_preview(row, None, None, None)
    edits = captured[0].options.native_edits
    if has_music and choice in {"off", "lower"}:
        assert edits.music == choice
    else:
        assert edits is None
