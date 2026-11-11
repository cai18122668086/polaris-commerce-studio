import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.motion_library import atomic_json, sha256
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from tests.test_video_editing_tasks import setup_source
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def completed_transcript(video, tmp_path):
    client, auth, ws, user, settings, project, source = setup_source(video, tmp_path)
    task = client.post(
        base(ws) + "/editing-tasks",
        json={
            "request_id": str(uuid4()),
            "source_id": source,
        },
    ).json()
    file = settings.video_editing_tasks_dir / task["id"] / "fixture" / "transcript.json"
    with client.app.state.session_factory() as session:
        record = session.get(EditingSourceRecord, source)
        transcript = Transcript(
            audio_sha256="a" * 64,
            source_sha256=record.media_sha256,
            duration_ms=1000,
            provider="boundary_fixture",
            model="fixture",
            language="zh",
            utterances=[],
            tokens=[TranscriptToken(id="t0", text="洗玩。", start_ms=100, end_ms=700)],
        )
        atomic_json(file, transcript.model_dump(mode="json"))
        row = session.get(EditingTaskRecord, task["id"])
        row.status = row.stage = "completed"
        artifact_id = str(uuid4())
        session.add(
            EditingArtifactRecord(
                id=artifact_id,
                task_id=task["id"],
                role="transcript",
                path=str(file),
                mime="application/json",
                sha256=sha256(file),
                bytes=file.stat().st_size,
                duration_ms=None,
            )
        )
        session.commit()
    return client, auth, ws, settings, source, task, artifact_id, file


def test_revision_is_immutable_replayable_and_new_job_preserves_original(
    video, tmp_path
):
    client, _, ws, settings, source, task, artifact, file = completed_transcript(
        video, tmp_path
    )
    original_sha = sha256(file)
    url = base(ws) + "/editing-tasks/" + task["id"]
    view = client.get(url + "/transcript")
    assert view.status_code == 200, view.text
    assert view.json()["text"] == "洗玩。"
    assert str(tmp_path) not in view.text
    body = {
        "request_id": str(uuid4()),
        "base_transcript_artifact_id": artifact,
        "corrected_text": "洗碗。",
    }
    saved = client.post(url + "/transcript-revisions", json=body)
    assert saved.status_code == 200, saved.text
    revision = saved.json()
    assert revision["text_status"] == "operator_candidate"
    assert revision["timing_review"] == "unreviewed"
    assert revision["changes"][0]["before"] == "玩"
    assert client.post(url + "/transcript-revisions", json=body).json() == revision
    assert (
        client.post(
            url + "/transcript-revisions", json={**body, "corrected_text": "另一版"}
        ).status_code
        == 409
    )
    assert client.get(url + "/transcript-revisions").json() == [revision]
    new_body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {
            "transcript_revision_id": revision["id"],
            "source_subtitles": "none",
        },
    }
    assert client.post(base(ws) + "/editing-tasks", json=new_body).status_code == 503
    settings.video_editing_alignment_enabled = True
    new_task = client.post(base(ws) + "/editing-tasks", json=new_body)
    assert new_task.status_code == 200, new_task.text
    assert new_task.json()["id"] != task["id"]
    assert new_task.json()["options"]["transcript_revision_id"] == revision["id"]
    assert client.get(url).json()["status"] == "completed"
    assert sha256(file) == original_sha
    denied = {**body, "request_id": str(uuid4()), "text_status": "user_corrected"}
    assert client.post(url + "/transcript-revisions", json=denied).status_code == 422
    accepted = client.post(
        url + "/transcript-revisions", json={**denied, "attests_spoken_text": True}
    )
    assert (
        accepted.status_code == 200
        and accepted.json()["text_status"] == "user_corrected"
    )
    assert accepted.json()["timing_review"] == "unreviewed"
    child = client.post(
        url + "/transcript-revisions",
        json={
            **body,
            "request_id": str(uuid4()),
            "parent_revision_id": revision["id"],
            "corrected_text": "洗碗！",
        },
    )
    assert child.status_code == 200, child.text
    assert child.json()["parent_revision_id"] == revision["id"]
    assert child.json()["changes"][0]["before"] == "。"
    assert child.json()["changes"][0]["after"] == "！"


def test_revision_cannot_cross_task_source_or_owner(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, settings, source, task, artifact, _ = completed_transcript(
        video, tmp_path
    )
    url = base(ws) + "/editing-tasks/" + task["id"]
    body = {
        "request_id": str(uuid4()),
        "base_transcript_artifact_id": artifact,
        "corrected_text": "洗碗。",
    }
    revision = client.post(url + "/transcript-revisions", json=body).json()
    other_task = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    ).json()
    assert (
        client.post(
            base(ws) + "/editing-tasks/" + other_task["id"] + "/transcript-revisions",
            json={**body, "request_id": str(uuid4())},
        ).status_code
        == 404
    )
    settings.video_editing_alignment_enabled = True
    with client.app.state.session_factory() as session:
        original_source = session.get(EditingSourceRecord, source)
        new_source = str(uuid4())
        session.add(
            EditingSourceRecord(
                id=new_source,
                workspace_id=original_source.workspace_id,
                owner_user_id=original_source.owner_user_id,
                project_id=original_source.project_id,
                kind="fixture",
                media_path=original_source.media_path,
                media_sha256=original_source.media_sha256,
            )
        )
        session.commit()
    assert (
        client.post(
            base(ws) + "/editing-tasks",
            json={
                "request_id": str(uuid4()),
                "source_id": new_source,
                "options": {"transcript_revision_id": revision["id"]},
            },
        ).status_code
        == 404
    )
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.get(url + "/transcript").status_code in (403, 404)
    assert client.get(url + "/transcript-revisions").status_code in (403, 404)
    assert client.post(url + "/transcript-revisions", json=body).status_code in (
        403,
        404,
    )


def test_correction_migration_roundtrip_preserves_existing_rows(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0044_editing_transcript_revisions.py"
    )
    spec = importlib.util.spec_from_file_location("transcript_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'corrections.db'}")
    with engine.begin() as connection:
        for table in (
            "users",
            "workspaces",
            "video_projects",
            "video_editing_sources",
            "video_editing_tasks",
            "video_editing_artifacts",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(text("INSERT INTO users VALUES ('preserved-user')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert (
            len(
                inspect(connection).get_unique_constraints(
                    "video_editing_transcript_revisions"
                )
            )
            == 1
        )
        migration.downgrade()
        assert (
            "video_editing_transcript_revisions"
            not in inspect(connection).get_table_names()
        )
        assert connection.scalar(text("SELECT id FROM users")) == "preserved-user"
    engine.dispose()
