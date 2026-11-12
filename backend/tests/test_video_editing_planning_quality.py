"""Incomplete automatic subtitles must fail before a new paid plan is queued."""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.errors import ApiError
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_planner import build_request
from app.video_editing_planning_quality import (
    NATIVE_BINDING_POLICY,
    NATIVE_BINDING_PROMPT,
    require_reference_transcript,
)
from app.video_editing_task_models import EditingArtifactRecord, EditingSourceRecord
from tests.test_video_editing_planning_tasks import create, setup

pytest_plugins = ["tests.test_video_projects"]

REFERENCE = (
    "随手拍一张产品图就能生成全套商品主图和详情页，今天一分钟教会大家怎么做。"
    "先准备一张产品白底图，再选择目标平台。"
)
LINEAGE = {"generation_script_snapshot": "matched"}


def transcript(text):
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=1000,
        provider="fixture",
        model="fixture",
        language="zh",
        reference_text=REFERENCE,
        reference_matches=False,
        tokens=[TranscriptToken(id="t0", text=text, start_ms=0, end_ms=1000)],
        utterances=[],
    )


def test_missing_sentences_require_review_but_minor_typos_do_not():
    with pytest.raises(ApiError) as error:
        require_reference_transcript(
            transcript("今今天一分教一张品图图"), "generation_task", LINEAGE
        )
    assert error.value.code == "EDITING_TRANSCRIPT_REVIEW_REQUIRED"
    require_reference_transcript(
        transcript(REFERENCE.replace("今天", "今今天").replace("白底图", "白地图片")),
        "generation_task",
        LINEAGE,
    )


@pytest.mark.parametrize(
    "kind,lineage,status",
    [
        ("upload_asset", LINEAGE, "automatic"),
        ("generation_task", {"generation_script_snapshot": "unavailable"}, "automatic"),
        ("generation_task", LINEAGE, "operator_candidate"),
        ("generation_task", LINEAGE, "user_corrected"),
    ],
)
def test_reference_is_only_a_guard_for_our_verified_automatic_transcript(
    kind, lineage, status
):
    candidate = transcript("今今天一分教一张品图图")
    candidate.text_status = status
    require_reference_transcript(candidate, kind, lineage)


def test_api_does_not_dispatch_or_create_paid_task_for_incomplete_asr(
    video, tmp_path, monkeypatch
):
    client, _, ws, settings, source_id, task, _ = setup(video, tmp_path, monkeypatch)
    dispatched = []
    client.app.state.editing_planning_dispatcher = dispatched.append
    with client.app.state.session_factory() as session:
        source = session.get(EditingSourceRecord, source_id)
        source.kind = "generation_task"
        source.details = {**source.details, "generation_lineage": LINEAGE}
        artifact = session.scalar(
            select(EditingArtifactRecord).where(
                EditingArtifactRecord.task_id == task["id"],
                EditingArtifactRecord.role == "transcript",
            )
        )
        path = Path(artifact.path)
        data = read_json(path)
        data.update(reference_text=REFERENCE, reference_matches=False)
        atomic_json(path, data)
        artifact.sha256, artifact.bytes = sha256(path), path.stat().st_size
        session.commit()
    result = create(client, ws, task["id"])
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == "EDITING_TRANSCRIPT_REVIEW_REQUIRED"
    assert dispatched == []


def test_new_binding_prompt_is_opt_in_and_old_frozen_request_replays(
    tmp_path, monkeypatch
):
    atomic_json(tmp_path / "catalog/groups.json", {"groups": []})
    monkeypatch.setattr("app.video_editing_planner.rule_pack", lambda _: {"rules": []})
    monkeypatch.setattr("app.video_editing_planner.catalog_index", lambda *a, **kw: [])
    candidate = transcript(REFERENCE)
    old_body, old_evidence = build_request(candidate, tmp_path, "fixture")
    replay, replay_evidence = build_request(
        candidate, tmp_path, "fixture", prepared_request=old_body
    )
    assert replay == old_body
    assert replay_evidence["request_sha256"] == old_evidence["request_sha256"]
    assert NATIVE_BINDING_PROMPT not in old_body["messages"][0]["content"]
    runtime = {
        "version": "fixture",
        "groups": {},
        "unavailable_template_groups": {},
        "native_binding_policy": NATIVE_BINDING_POLICY,
    }
    new_body, new_evidence = build_request(
        candidate, tmp_path, "fixture", runtime=runtime
    )
    assert NATIVE_BINDING_PROMPT in new_body["messages"][0]["content"]
    assert new_evidence["request_sha256"] != old_evidence["request_sha256"]
