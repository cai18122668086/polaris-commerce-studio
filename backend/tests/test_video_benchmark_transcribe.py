"""小红书 benchmark transcription runs on the editing worker, fenced and resumable."""

import json
import subprocess
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import video_benchmark_transcribe as worker
from app.main import create_app
from app.video_assistance import process
from app.video_assistance_models import VideoAssistanceRecord
from app.video_assistance_provider import VideoAssistanceProvider
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, payload

NOTE = "6a7ebcc10000000025013050"
MEDIA = "https://sns-video-v6.xhscdn.com/stream/1/note.mp4"


class FakeAsr:
    """Stands in for `python -m app.video_benchmark_asr`; records its arguments."""

    def __init__(self, output):
        self.output, self.args = output, []

    def __call__(self, args, **_):
        self.args.append(args)
        text = json.dumps(self.output, ensure_ascii=False)

        class Out:
            @staticmethod
            def read():
                return text

        class Done:
            stdout = Out()

            @staticmethod
            def poll():
                return 0

        return Done()


@pytest.fixture
def xhs(tmp_path, monkeypatch):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={
            "video_benchmark_search_enabled": True,
            "video_extract_enabled": True,
            "video_extract_api_key": SecretStr("local-fixture"),
        }
    )
    calls = []

    def send(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["platform"] == "xiaohongshu" and body["action"] == "search"
        assert body["params"]["sort"] == "most_liked"
        row = {
            "id": NOTE,
            "url": "https://www.xiaohongshu.com/explore/" + NOTE,
            "title": "护手霜",
            "text": "正文",
            "like_count": 10,
            "collect_count": 5,
            "is_video": True,
            "video_url": MEDIA.replace("https://", "http://"),
            "duration_sec": 30,
        }
        return httpx.Response(200, json={"results": [row]})

    app = create_app(settings, auth)
    app.state.video_assistance_provider = VideoAssistanceProvider(
        settings, httpx.MockTransport(send)
    )
    dispatched = []
    monkeypatch.setattr(
        worker, "dispatch", lambda task_id: dispatched.append(task_id) or True
    )
    with TestClient(app) as client:
        workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
        root = f"/api/v1/video-studio/workspaces/{workspace_id}"
        yield app, client, root, calls, dispatched, settings


def start(client, root):
    project = str(uuid4())
    assert client.put(f"{root}/projects/{project}", json=payload()).status_code == 200
    page = client.post(
        f"{root}/benchmark-searches",
        json={
            "request_id": str(uuid4()),
            "project_id": project,
            "expected_revision": 1,
            "keyword": "护手霜",
            "platform": "xiaohongshu",
        },
    ).json()
    jobs = client.post(
        f"{root}/benchmark-extractions",
        json={
            "project_id": project,
            "expected_revision": 1,
            "items": [{"search_task_id": page["id"], "platform_id": NOTE}],
        },
    )
    assert jobs.status_code == 200, jobs.text
    return jobs.json()[0]["id"]


def row(app, task_id):
    with app.state.session_factory() as session:
        return session.get(VideoAssistanceRecord, task_id)


def test_queued_for_the_worker_then_transcribed_once(xhs, monkeypatch):
    app, client, root, calls, dispatched, settings = xhs
    task_id = start(client, root)
    assert dispatched == [task_id]
    queued = row(app, task_id)
    assert (queued.status, queued.stage) == ("running", worker.QUEUED)
    # The search page's file is reused: no extra paid detail call.
    assert queued.inputs["media_url"] == MEDIA

    asr = FakeAsr({"text": "你真的会涂护手霜吗？先洗手再擦干。", "segments": []})
    monkeypatch.setattr(subprocess, "Popen", asr)
    worker.transcribe(task_id, settings, app.state.session_factory)
    worker.transcribe(task_id, settings, app.state.session_factory)  # redelivery
    assert len(asr.args) == 1 and asr.args[0][-2] == MEDIA
    done = row(app, task_id)
    assert done.status == "completed"
    assert done.result["text"].startswith("你真的会涂护手霜吗")
    assert len(calls) == 1


def test_no_speech_fails_cleanly_and_a_lost_broker_is_resumable(xhs, monkeypatch):
    app, client, root, calls, dispatched, settings = xhs
    task_id = start(client, root)
    monkeypatch.setattr(subprocess, "Popen", FakeAsr({"text": "", "segments": []}))
    monkeypatch.setattr(worker, "note_text", lambda settings, inputs: "减脂早餐 #早餐#")
    worker.transcribe(task_id, settings, app.state.session_factory)
    failed = row(app, task_id)
    assert (failed.status, failed.error_code) == ("failed", "VIDEO_TRANSCRIPT_EMPTY")

    monkeypatch.setattr(worker, "dispatch", lambda task_id: False)
    with app.state.session_factory() as session:
        again = session.get(VideoAssistanceRecord, task_id)
        again.status, again.stage = "queued", "submitting"
        session.commit()
    process(app.state.session_factory, task_id, app.state.video_assistance_provider)
    assert row(app, task_id).status == "awaiting_resume"
    listed = client.get(
        root + "/assistance-tasks", params={"project_id": row(app, task_id).project_id}
    )
    assert any(job["id"] == task_id and job["can_resume"] for job in listed.json())


@pytest.mark.parametrize(
    ("text", "seconds", "ok"),
    [
        (
            "City, let's come a love and some a song skin. The sky with a farmer",
            59,
            False,
        ),
        ("哎，你什么？", 42, False),
        (
            "你真的会涂护手霜吗？不洗手直接涂，每次只涂一点点，厚厚一层却不按摩。",
            20,
            True,
        ),
    ],
)
def test_lyrics_and_stray_words_are_not_a_spoken_script(text, seconds, ok):
    assert worker.spoken({"text": text, "duration_seconds": seconds}) is ok


def test_music_only_video_uses_the_full_note_text_and_says_so(xhs, monkeypatch):
    app, client, root, calls, dispatched, settings = xhs
    task_id = start(client, root)
    monkeypatch.setattr(
        subprocess, "Popen", FakeAsr({"text": "La la la", "duration_seconds": 40})
    )
    recipe = (
        "西葫芦擦丝加盐杀水，挤干后打两个鸡蛋，加一勺面粉拌匀。"
        "平底锅少油小火煎到两面金黄，夹上生菜和番茄就是低卡三明治。"
        "十分钟搞定，饱腹感很强，减脂期早餐吃它一上午都不会饿。"
    )
    monkeypatch.setattr(worker, "note_text", lambda settings, inputs: recipe)
    worker.transcribe(task_id, settings, app.state.session_factory)
    done = row(app, task_id)
    assert done.status == "completed" and done.result["source"] == "note_text"
    assert done.result["text"] == recipe
