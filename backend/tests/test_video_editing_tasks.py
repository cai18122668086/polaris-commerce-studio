"""Business isolation and durable cancellation, without paid/video providers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from wave import open as open_wave

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app import video_editing_worker as worker
from app.main import create_app
from app.motion_library import atomic_json, sha256
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_display_rotation import display_rotation
from app.video_editing_pipeline import measured_source_frame
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingAttemptRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from app.video_editing_worker import process
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


@pytest.mark.parametrize(
    ("matrix", "angle", "expected", "native"),
    [
        ((0, -65536, 65536, 0), 90, (720, 1280), True),
        ((0, 65536, -65536, 0), -90, (720, 1280), True),
        ((-65536, 0, 0, -65536), 180, (1280, 720), False),
        ((65536, 0, 0, -65536), 0, (1280, 720), False),
        ((65536, 1, 0, 65536), 0, (1280, 720), False),
    ],
)
def test_display_frame_accepts_only_canonical_quarter_turns(
    matrix, angle, expected, native
):
    a, b, c, d = matrix
    video = {
        "codec_type": "video",
        "width": 1280,
        "height": 720,
        "sample_aspect_ratio": "1:1",
        "side_data_list": [
            {
                "side_data_type": "Display Matrix",
                "rotation": angle,
                "displaymatrix": (
                    f"\n00000000: {a} {b} 0\n00000001: {c} {d} 0\n"
                    f"00000002: 0 {-min(b, 0) * 1280} 1073741824\n"
                ),
            }
        ],
    }
    frame = measured_source_frame({"streams": [video]})
    assert (frame.width, frame.height) == expected
    assert frame.supports_native_portrait is native
    if a == 65536:
        with pytest.raises(ValueError, match="verified quarter turn"):
            display_rotation(video)


def setup_source(video, tmp_path):
    client, auth, ws, user, settings = video
    package = tmp_path / "library"
    package.mkdir()
    (package / "adapter.py").write_text("# API test: never rendered\n")
    settings.video_editing_enabled = True
    settings.video_editing_library_dir = package
    settings.video_editing_tasks_dir = tmp_path / "editing"
    client.app.state.editing_dispatcher = lambda task_id: None
    pid = str(uuid4())
    assert client.put(base(ws) + "/projects/" + pid, json=payload()).status_code == 200
    result = client.post(
        base(ws) + "/editing-sources",
        data={"project_id": pid},
        files={
            "file": ("scope-test.mp4", b"not-real-media-api-boundary-only", "video/mp4")
        },
    )
    assert result.status_code == 200, result.text
    return client, auth, ws, user, settings, pid, result.json()["id"]


def test_task_replay_cancel_retry_and_no_paths_exposed(video, tmp_path):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    body = {"request_id": str(uuid4()), "source_id": source}
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    task_id = first.json()["id"]
    assert client.post(url, json=body).json()["id"] == task_id
    assert (
        client.post(url, json={**body, "options": {"language": "en"}}).status_code
        == 409
    )
    assert "media_path" not in first.text and str(tmp_path) not in first.text
    assert client.post(url + f"/{task_id}/cancel").json()["cancel_requested"]
    process(task_id, settings, client.app.state.session_factory)
    cancelled = client.get(url + f"/{task_id}").json()
    assert cancelled["status"] == "cancelled" and cancelled["artifacts"] == []
    assert client.post(url + f"/{task_id}/retry").json()["status"] == "queued"
    assert client.post(url + f"/{task_id}/retry").status_code == 409
    with client.app.state.session_factory() as session:
        attempts = list(session.scalars(select(EditingAttemptRecord)))
        assert attempts == []  # Queued cancellation never needs a live worker.


def test_source_upload_retries_keep_one_immutable_owned_input(
    video, tmp_path, monkeypatch
):
    client, auth, ws, _, settings, pid, old_source = setup_source(video, tmp_path)
    endpoint = base(ws) + "/editing-sources"
    request_id = str(uuid4())

    def upload(
        content=b"unique oral source", project=pid, mime="video/mp4", via=client
    ):
        return via.post(
            endpoint,
            data={"project_id": project, "request_id": request_id},
            files={"file": ("spoken.mp4", content, mime)},
        )

    assert upload(b"").json()["error"]["code"] == "EDITING_SOURCE_EMPTY"
    barrier = Barrier(2)
    commit = Session.commit

    def concurrent_commit(session):
        if any(isinstance(row, EditingSourceRecord) for row in session.new):
            barrier.wait(timeout=12)
        return commit(session)

    with (
        TestClient(create_app(settings, auth)) as other_client,
        monkeypatch.context() as patches,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        patches.setattr(Session, "commit", concurrent_commit)
        first = pool.submit(upload)
        second = pool.submit(upload, via=other_client)
        a = first.result().raise_for_status().json()
        b = second.result().raise_for_status().json()
    assert a == b and a["id"] != old_source
    assert a == upload().raise_for_status().json()
    second_project = str(uuid4())
    client.put(
        base(ws) + "/projects/" + second_project, json=payload()
    ).raise_for_status()
    for conflict in (
        upload(b"another oral source"),
        upload(project=second_project),
        upload(mime="video/webm"),
    ):
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "EDITING_SOURCE_REQUEST_REUSED"
    with client.app.state.session_factory() as session:
        row = session.get(EditingSourceRecord, a["id"])
        stored = Path(row.media_path)
        assert stored.read_bytes() == b"unique oral source"
        assert sha256(stored) == a["sha256"]
        assert set(session.scalars(select(EditingSourceRecord.id))) == {
            old_source,
            a["id"],
        }
    source_dir = settings.video_editing_tasks_dir / "sources"
    assert len(list(source_dir.iterdir())) == 2
    stored.write_bytes(b"changed oral source")
    response = upload()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EDITING_SOURCE_CHANGED"
    assert stored.read_bytes() == b"changed oral source"
    assert len(list(source_dir.iterdir())) == 2


@pytest.mark.parametrize(
    ("matching_audio", "width", "height", "pixel_ratio", "can_plan"),
    [
        (True, 720, 1280, "1:1", True),
        (True, 1280, 720, "1:1", False),
        (True, 720, 1280, "4:3", False),
        (False, 720, 1280, "1:1", False),
    ],
)
def test_direct_transcription_delivers_checked_words_without_rendering(
    video, tmp_path, monkeypatch, matching_audio, width, height, pixel_ratio, can_plan
):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    body = {
        "request_id": str(uuid4()),
        "source_id": source,
        "options": {"mode": "transcript", "source_subtitles": "none"},
    }
    started = client.post(url, json=body).raise_for_status().json()
    assert client.post(url, json=body).json()["id"] == started["id"]

    def prepare(_path, digest, root, _settings, _guard):
        audio = root / "input/speech.wav"
        audio.parent.mkdir(parents=True)
        with open_wave(str(audio), "wb") as track:
            track.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            track.writeframes(bytes(32000))
        return {
            "source_sha256": digest,
            "audio_sha256": sha256(audio),
            "duration_ms": 1000,
            "clock": {"audio_offset_ms": 10, "analysis_audio_end_ms": 1010},
            "probe": {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": width,
                        "height": height,
                        "sample_aspect_ratio": pixel_ratio,
                    }
                ]
            },
        }

    def load(_id, root, prepared, _snapshot, _settings, _guard, stage):
        stage("transcribing")
        transcript = Transcript(
            source_sha256=prepared["source_sha256"],
            audio_sha256=prepared["audio_sha256"] if matching_audio else "0" * 64,
            duration_ms=1000,
            language="zh",
            provider="fixture",
            model="fixture",
            tokens=[TranscriptToken(id="t0", text="口播", start_ms=60, end_ms=700)],
            utterances=[],
        )
        atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
        return transcript

    def forbidden(*args, **kwargs):
        pytest.fail("Direct transcription must never compile or export a film")

    monkeypatch.setattr(worker, "verify_package", lambda _: None)
    monkeypatch.setattr(worker, "prepare", prepare)
    monkeypatch.setattr(worker, "load_transcript", load)
    monkeypatch.setattr(worker, "compile_baseline", forbidden)
    monkeypatch.setattr(worker, "native_export", forbidden)
    process(started["id"], settings, client.app.state.session_factory)
    endpoint = url + "/" + started["id"]
    result = client.get(endpoint).raise_for_status().json()
    if not matching_audio:
        assert result["status"] == "failed" and result["artifacts"] == []
        assert result["error_code"] == "EDITING_TRANSCRIPT_CHANGED"
        return
    assert (result["status"], result["stage"]) == ("completed", "transcript_ready")
    assert result["source_frame"] == {
        "width": width,
        "height": height,
        "supports_native_portrait": can_plan,
    }
    artifacts = {a["role"]: a for a in result["artifacts"]}
    assert set(artifacts) == {"transcript", "transcript_audio"}
    view = client.get(endpoint + "/transcript").raise_for_status().json()
    assert view["text"] == "口播" and view["analysis_audio_offset_ms"] == 10
    audio = client.get(
        artifacts["transcript_audio"]["url"], headers={"Range": "bytes=0-43"}
    )
    assert audio.status_code == 206 and audio.headers["content-type"] == "audio/wav"
    assert audio.content.startswith(b"RIFF")
    assert client.get(base(ws) + "/editing-works").json()["items"] == []
    planned = client.post(
        endpoint + "/planning-tasks", json={"request_id": str(uuid4())}
    )
    if not can_plan:
        assert planned.status_code == 409
        assert planned.json()["error"]["code"] == "EDITING_ORIENTATION_REVIEW_REQUIRED"
        return
    assert planned.status_code == 200, planned.text
    assert planned.json()["base_transcript_sha256"] == artifacts["transcript"]["sha256"]


def test_task_and_source_are_scoped_to_owner_and_project(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, _, _, pid, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    created = client.post(
        url, json={"request_id": str(uuid4()), "source_id": source}
    ).json()
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.get(url + "/" + created["id"]).status_code in (403, 404)
    assert client.post(
        url, json={"request_id": str(uuid4()), "source_id": source}
    ).status_code in (403, 404)
    assert client.post(
        base(ws) + "/editing-sources",
        data={"project_id": pid},
        files={"file": ("cross.mp4", b"x", "video/mp4")},
    ).status_code in (403, 404)


def test_valid_worker_lease_cannot_be_stolen_and_expired_run_is_fenced(video, tmp_path):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    created = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    ).json()
    factory = client.app.state.session_factory
    old_token = str(uuid4())
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        row.status, row.owner_token = "running", old_token
        row.lease_until = datetime.now(UTC) + timedelta(minutes=2)
        session.commit()
    process(created["id"], settings, factory)
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.owner_token == old_token and row.attempts == 0
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        row.cancel_requested = True
        session.commit()
    process(created["id"], settings, factory)
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert (
            row.status == "cancelled" and row.owner_token is None and row.attempts == 1
        )


def test_recovery_reserves_delivery_and_broker_loss_keeps_durable_job(
    video, tmp_path, monkeypatch
):
    from app.video_editing_worker import celery_app, recover

    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    created = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    ).json()
    factory = client.app.state.session_factory
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: sent.append((a, kw)))
    assert recover(factory) == 1
    assert recover(factory) == 0
    assert len(sent) == 1
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.status == "queued" and row.attempts == 0
        row.checkpoint = {**row.checkpoint, "dispatch_not_before": 0}
        session.commit()

    def unavailable(*a, **kw):
        raise ConnectionError("test broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    assert recover(factory) == 0
    with factory() as session:
        row = session.get(EditingTaskRecord, created["id"])
        assert row.status == "queued" and row.checkpoint["dispatch_not_before"] > 0


def test_attempt_storage_failure_releases_editing_lease(video, tmp_path):
    client, _, ws, _, settings, _, source = setup_source(video, tmp_path)
    tasks = base(ws) + "/editing-tasks"
    created = (
        client.post(tasks, json={"request_id": str(uuid4()), "source_id": source})
        .raise_for_status()
        .json()
    )
    task_id = created["id"]
    blocked = settings.video_editing_tasks_dir / task_id
    blocked.touch()
    factory = client.app.state.session_factory

    process(task_id, settings, factory)

    failed = client.get(f"{tasks}/{task_id}").raise_for_status().json()
    assert failed["status"] == "failed"
    assert failed["error_code"] == "EDITING_TASK_STORAGE_UNAVAILABLE"
    assert failed["artifacts"] == []
    with factory() as session:
        task = session.get(EditingTaskRecord, task_id)
        attempt = session.scalar(
            select(EditingAttemptRecord).where(EditingAttemptRecord.task_id == task_id)
        )
        assert task.owner_token is None and task.lease_until is None
        assert (attempt.status, attempt.error_code) == ("failed", failed["error_code"])

    blocked.unlink()
    retry = client.post(f"{tasks}/{task_id}/retry").raise_for_status().json()
    assert (retry["id"], retry["status"], retry["attempts"]) == (task_id, "queued", 1)


def test_create_task_never_connects_to_broker_in_request_thread(
    video, tmp_path, monkeypatch
):
    from app.video_editing_worker import celery_app

    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    del client.app.state.editing_dispatcher

    def forbidden(*args, **kwargs):
        raise AssertionError("API must only persist, never publish or transcribe")

    monkeypatch.setattr(celery_app, "send_task", forbidden)
    result = client.post(
        base(ws) + "/editing-tasks",
        json={"request_id": str(uuid4()), "source_id": source},
    )
    assert result.status_code == 200 and result.json()["status"] == "queued"


def test_preview_confirmation_is_exact_owned_and_replayable(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, _, settings, _, source = setup_source(video, tmp_path)
    url = base(ws) + "/editing-tasks"
    old = client.post(url, json={"request_id": str(uuid4()), "source_id": source})
    assert old.status_code == 200
    tid = old.json()["id"]
    assert "delivery" not in old.json()["options"]
    root = settings.video_editing_tasks_dir / tid
    root.mkdir()
    preview, master = root / "preview.mp4", root / "master.mp4"
    preview.write_bytes(b"proxy test fixture")
    master.write_bytes(b"master test fixture")
    preview_id, final_id = str(uuid4()), str(uuid4())
    preview_sha, final_sha = sha256(preview), sha256(master)
    with client.app.state.session_factory() as session:
        row = session.get(EditingTaskRecord, tid)
        row.options = {
            **row.options,
            "mode": "native_plan",
            "native_plan_id": str(uuid4()),
            "delivery": "preview_first",
        }
        row.status, row.stage, row.attempts = "awaiting_review", "preview_ready", 1
        for identity, path, role in (
            (preview_id, preview, "preview"),
            (final_id, master, "staged_final"),
        ):
            session.add(
                EditingArtifactRecord(
                    id=identity,
                    task_id=tid,
                    role=role,
                    path=str(path),
                    mime="video/mp4",
                    bytes=path.stat().st_size,
                    sha256=sha256(path),
                    duration_ms=2000,
                    validation={"decoded": True, "native_render_sha256": final_sha},
                )
            )
        session.commit()
    task_url = url + "/" + tid
    works_url = base(ws) + "/editing-works"
    confirm_url = task_url + "/confirm-export"
    artifact_url = task_url + "/artifacts/"
    body = {"preview_artifact_id": preview_id, "preview_sha256": preview_sha}
    waiting = client.get(task_url).json()
    assert waiting["status"] == "awaiting_review"
    assert [item["role"] for item in waiting["artifacts"]] == ["preview"]
    assert client.get(works_url).json() == {"items": [], "next_before": None}
    assert client.get(artifact_url + final_id).status_code == 404
    assert client.get(artifact_url + preview_id).content == preview.read_bytes()
    assert (
        client.post(confirm_url, json={**body, "preview_sha256": "0" * 64}).status_code
        == 409
    )
    identity = auth.identity
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.post(confirm_url, json=body).status_code in {403, 404}
    auth.identity = identity
    master.write_bytes(b"X" * master.stat().st_size)
    assert (
        client.post(confirm_url, json=body).json()["error"]["code"]
        == "EDITING_EXPORT_CHANGED"
    )
    assert client.get(artifact_url + final_id).status_code == 404
    master.write_bytes(b"master test fixture")
    confirmed = client.post(confirm_url, json=body)
    assert confirmed.status_code == 200, confirmed.text
    record = confirmed.json()
    assert record["status"] == "completed" and record["attempts"] == 1
    assert (
        record["review"]["delivery"] == "confirmed"
        and record["review"]["visual"] == "unreviewed"
    )
    assert (
        next(a for a in record["artifacts"] if a["role"] == "final")["id"] == final_id
    )
    assert client.get(artifact_url + final_id).content == master.read_bytes()
    (work,) = client.get(works_url).json()["items"]
    assert work["task_id"] == tid
    assert work["project_title"] == "演示产品"
    assert work["mode"] == "native_plan"
    assert work["final"]["url"] == artifact_url + final_id
    assert "preview" not in work and "path" not in work["final"]
    assert client.post(confirm_url, json=body).json() == record
    assert (
        client.post(
            confirm_url, json={**body, "preview_artifact_id": str(uuid4())}
        ).status_code
        == 409
    )


def test_editing_works_search_cursor_and_owner_scope(video, tmp_path):
    from tests.test_auth_external import verified_identity

    client, auth, ws, _, _, project, source = setup_source(video, tmp_path)
    task_url = base(ws) + "/editing-tasks"
    works_url = base(ws) + "/editing-works"
    ids = [
        client.post(
            task_url, json={"request_id": str(uuid4()), "source_id": source}
        ).json()["id"]
        for _ in range(4)
    ]
    with client.app.state.session_factory() as session:
        for tid in ids[:3]:
            task = session.get(EditingTaskRecord, tid)
            task.status = task.stage = "completed"
            task.created_at = datetime(2026, 11, 9, 6, tzinfo=UTC)
            if tid == ids[2]:
                task.options = {
                    **task.options,
                    "mode": "native_plan",
                    "native_plan_id": str(uuid4()),
                    "delivery": "preview_first",
                }
            session.add(
                EditingArtifactRecord(
                    id=str(uuid4()),
                    task_id=tid,
                    role="final",
                    path=str(tmp_path / "not-served-by-the-list.mp4"),
                    mime="video/mp4",
                    bytes=120,
                    sha256="a" * 64,
                    duration_ms=2000,
                )
            )
        session.commit()
    high, low = sorted(ids[:2], reverse=True)
    first = client.get(works_url, params={"limit": 1, "keyword": "演示"}).json()
    assert [work["task_id"] for work in first["items"]] == [high]
    assert first["next_before"] == high
    second = client.get(
        works_url, params={"limit": 1, "before": high, "keyword": "演示"}
    ).json()
    assert [(work["task_id"], work["project_id"]) for work in second["items"]] == [
        (low, project)
    ]
    assert second["next_before"] is None
    assert client.get(works_url, params={"keyword": "%"}).json()["items"] == []
    artifact_queries = []

    def record_artifact_query(_connection, _cursor, statement, *_):
        if "FROM video_editing_artifacts" in statement:
            artifact_queries.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", record_artifact_query)
    try:
        recent = (
            client.get(task_url, params={"project_id": project})
            .raise_for_status()
            .json()
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_artifact_query)
    assert {row["id"] for row in recent} == set(ids)
    assert {row["id"] for row in recent if row["artifacts"]} == {high, low}
    assert len(artifact_queries) == 1
    detail_url = task_url + "/" + high
    assert client.get(detail_url, params={"project_id": project}).json()["id"] == high
    different_project = str(uuid4())
    client.put(
        base(ws) + "/projects/" + different_project, json=payload()
    ).raise_for_status()
    mismatch = client.get(detail_url, params={"project_id": different_project})
    assert (
        mismatch.status_code == 404
        and mismatch.json()["error"]["code"] == "EDITING_NOT_FOUND"
    )
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    unscoped = client.get(works_url)
    assert unscoped.status_code in {403, 404} or unscoped.json()["items"] == []
    assert client.get(works_url, params={"before": high}).status_code in {403, 404}
