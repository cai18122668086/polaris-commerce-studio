"""Covers come from our own origin: allow-listed CDNs only, cached once fetched."""

import httpx

from app import video_benchmark_covers as covers
from tests.test_video_benchmark_transcribe import NOTE, start, xhs  # noqa: F401

PREFETCH = covers.prefetch


def test_only_platform_cdns_are_fetched():
    assert covers.allowed("https://sns-note-i4.xhscdn.com/a.jpg")
    assert covers.allowed("https://p3-sign.douyinpic.com/x~tplv.jpeg?x-expires=1")
    assert not covers.allowed("http://sns-note-i4.xhscdn.com/a.jpg")
    assert not covers.allowed("https://evil.example/xhscdn.com.jpg")
    assert not covers.allowed("https://user:pw@p3.douyinpic.com/a.jpg")


def test_a_search_results_cover_is_served_and_cached(xhs, monkeypatch):  # noqa: F811
    app, client, root, calls, dispatched, settings = xhs
    fetched = []

    def send(request):
        fetched.append(str(request.url))
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8jpeg"
        )

    monkeypatch.setattr(covers, "TRANSPORT", httpx.MockTransport(send))
    monkeypatch.setattr(covers, "prefetch", PREFETCH)
    page = client.post(
        f"{root}/benchmark-searches",
        json={
            "request_id": "8b0d3a5e-1c55-4f61-9d3e-2a4f7b1c9e01",
            "project_id": start_project(client, root),
            "expected_revision": 1,
            "keyword": "护手霜",
            "platform": "xiaohongshu",
        },
    ).json()
    url = f"{root}/benchmark-covers/{page['id']}/{NOTE}"
    first = client.get(url)
    assert first.status_code == 200 and first.content == b"\xff\xd8jpeg"
    assert first.headers["content-type"] == "image/jpeg"
    assert client.get(url).status_code == 200
    assert len(fetched) == 1  # pre-fetched once with the search, then served from cache
    assert (
        fetched[0].startswith("https://sns-note-i4.xhscdn.com/")
        and "format/jpg" in fetched[0]
    )
    assert (
        client.get(f"{root}/benchmark-covers/{page['id']}/zzzzzzzzzzzz").status_code
        == 404
    )
    assert (
        client.get(f"{root}/benchmark-covers/{page['id']}/../../etc").status_code == 404
    )


def start_project(client, root):
    from uuid import uuid4

    from tests.test_video_projects import payload

    project = str(uuid4())
    assert client.put(f"{root}/projects/{project}", json=payload()).status_code == 200
    return project


def test_heic_covers_are_turned_into_jpeg(tmp_path, monkeypatch):
    settings = type(
        "S", (), {"video_editing_tasks_dir": tmp_path, "video_editing_ffmpeg": "ffmpeg"}
    )()
    monkeypatch.setattr(
        covers,
        "TRANSPORT",
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "image/heic"}, content=b"heic"
            )
        ),
    )
    monkeypatch.setattr(
        covers,
        "to_jpeg",
        lambda settings, body: b"\xff\xd8converted" if body == b"heic" else b"",
    )
    path, content_type = covers.fetch(
        settings,
        "t",
        "7514264713057815862",
        "https://p3-sign.douyinpic.com/a.heic?x-expires=1",
    )
    assert content_type == "image/jpeg" and path.read_bytes() == b"\xff\xd8converted"
    assert covers.cached(settings, "t", "7514264713057815862") == (path, "image/jpeg")
