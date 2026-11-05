"""Browser integration using the real persistence API and disposable identities/DB."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app
from app.video_generation import OWNED_IMAGE
from app.video_generation_models import VideoAvatarRecord
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_generation import FakeVideoProviders

ORIGIN = os.environ.get("VIDEO_STUDIO_ORIGIN", "http://127.0.0.1:3000")


def wav_fixture():
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    return out.getvalue()


async def verify(client):
    ws = client.get("/api/v1/workspaces").json()[0]["id"]
    api_root = f"/api/v1/video-studio/workspaces/{ws}"
    failure = None
    writes = []
    checks = []
    output = ROOT / "outputs/video-studio"
    output.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)

        async def setup(context):
            async def route_api(route):
                nonlocal failure
                request = route.request
                url = urlparse(request.url)
                path = url.path
                method = request.method
                if method != "GET" and not path.startswith("/api/v1/video-studio/"):
                    raise AssertionError("Unexpected non-video write: " + path)
                if path.startswith("/api/v1/video-studio/") or path in [
                    "/api/v1/me",
                    "/api/v1/workspaces",
                ]:
                    body = (
                        request.post_data_json
                        if method != "GET" and not path.endswith("/audio-files")
                        else None
                    )
                    if method != "GET":
                        writes.append(
                            {
                                "method": method,
                                "path": path,
                                "action": (body or {}).get("action"),
                                "request_id": (body or {}).get("request_id"),
                            }
                        )
                    if failure == "offline" and method == "PUT":
                        await route.abort()
                        return
                    response = (
                        client.request(
                            method,
                            path,
                            content=request.post_data_buffer,
                            headers={"Content-Type": request.headers["content-type"]},
                        )
                        if path.endswith("/audio-files")
                        else client.request(
                            method,
                            path + ("?" + url.query if url.query else ""),
                            json=body,
                        )
                    )
                    if (
                        failure == "lost-real"
                        and method == "POST"
                        and (body or {}).get("kind") == "lipsync"
                    ):
                        failure = None
                        assert response.status_code == 200, response.text
                        await route.abort()
                        return
                    await route.fulfill(
                        status=response.status_code,
                        body=response.content,
                        headers={
                            "Content-Type": response.headers.get(
                                "content-type", "application/json"
                            ),
                            "Cache-Control": "no-store",
                        },
                    )
                    return
                if path.endswith("/credits"):
                    body = {
                        "enforcement_enabled": False,
                        "balance_credits": 0,
                        "available_credits": 0,
                        "reserved_credits": 0,
                        "pricing": [],
                    }
                elif path.endswith("/creation-summary"):
                    body = {"active": 0, "needs_attention": 0}
                elif "announcements" in path:
                    body = {"items": []}
                else:
                    body = []
                await route.fulfill(json=body)

            await context.route("**/api/v1/**", route_api)
            page = await context.new_page()
            page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
            return page

        async def saved(page):
            await (
                page.get_by_label("项目保存状态", exact=True)
                .filter(has_text="已保存")
                .wait_for()
            )

        device_a = await browser.new_context(viewport={"width": 1440, "height": 1000})
        a = await setup(device_a)
        await a.goto(ORIGIN + "/video-studio")
        await a.get_by_role("button", name="创作视频", exact=True).click()
        await saved(a)
        await a.get_by_label("视频名称", exact=True).fill("持久化验收项目")
        await a.get_by_label("视频文案", exact=True).fill("第一版口播文案")
        await a.get_by_role("button", name="选择数字人", exact=False).first.click()
        await a.get_by_role("button", name="应用形象", exact=True).click()
        await a.get_by_role("button", name="选择声音", exact=False).first.click()
        await a.get_by_role("button", name="选择", exact=True).first.click()
        await a.get_by_role("button", name="应用声音", exact=True).click()
        await a.get_by_role("button", name="文案二创", exact=True).click()
        await a.get_by_label("产品事实").fill("验收产品，无香精，100毫升")
        await a.get_by_role("button", name="视频链接提取", exact=True).click()
        await a.get_by_placeholder("粘贴公开抖音视频链接").fill(
            "https://example.com/video-reference"
        )
        await a.get_by_role("button", name="提取文案", exact=False).click()
        await a.get_by_role("button", name="取消", exact=True).click()
        await saved(a)
        await a.get_by_role("button", name="存入文案库", exact=True).click()
        await saved(a)
        await a.get_by_role("button", name="生成视频", exact=True).click()
        await a.get_by_role("button", name="确认生成", exact=False).click()
        await a.get_by_role("dialog").wait_for(state="detached")
        await saved(a)
        project = client.get(api_root + "/projects").json()[0]
        pid = project["id"]
        assert project["content"]["product_facts"] == "验收产品，无香精，100毫升"
        assert (
            project["content"]["references"][0]["url"]
            == "https://example.com/video-reference"
        )
        assert client.get(api_root + "/generation-tasks").json()[0][
            "confirmed_version_id"
        ]
        await a.wait_for_timeout(3800)
        await a.screenshot(path=str(output / "persistence-editor-fixture.png"))
        checks.append(
            "device A saves draft, choices, product facts, "
            "reference, library version, confirmed version and generation task"
        )

        device_b = await browser.new_context(viewport={"width": 1440, "height": 1000})
        b = await setup(device_b)
        await b.goto(ORIGIN + f"/video-studio/create?project={pid}")
        await saved(b)
        assert (
            await b.get_by_label("视频文案", exact=True).input_value()
            == "第一版口播文案"
        )
        assert (
            await b.get_by_label("视频名称", exact=True).input_value()
            == "持久化验收项目"
        )
        assert (
            await b.evaluate("localStorage.getItem('polaris-video-studio-demo-v1')")
            is None
        )
        await b.get_by_text("温柔女声", exact=True).wait_for()
        await b.get_by_role("button", name="文案二创", exact=True).click()
        assert (
            await b.get_by_label("产品事实").input_value()
            == "验收产品，无香精，100毫升"
        )
        await b.get_by_role("button", name="视频链接提取", exact=True).click()
        assert (
            await b.get_by_placeholder("粘贴公开抖音视频链接").input_value()
            == "https://example.com/video-reference"
        )
        await b.get_by_role("button", name="取消", exact=True).click()
        checks.append(
            "separate browser context with empty localStorage "
            "resumes same account project"
        )

        await a.get_by_label("视频文案", exact=True).fill("设备A的新版本")
        await saved(a)
        await b.get_by_label("视频文案", exact=True).fill("设备B保留的冲突文案")
        await b.get_by_role("alert").filter(has_text="另一设备").wait_for()
        assert (
            await b.get_by_label("视频文案", exact=True).input_value()
            == "设备B保留的冲突文案"
        )
        assert (
            client.get(api_root + f"/projects/{pid}").json()["content"]["draft"]["text"]
            == "设备A的新版本"
        )
        await b.get_by_role("button", name="另存项目", exact=True).click()
        await saved(b)
        assert len(client.get(api_root + "/projects").json()) == 2
        checks.append(
            "stale device gets conflict, retains text and saves as a separate project"
        )

        before = len(client.get(api_root + "/generation-tasks").json())
        failure = "lost-real"
        await a.get_by_role("button", name="生成视频", exact=True).click()
        await a.get_by_role("button", name="确认生成", exact=False).click()
        await a.get_by_role("dialog").get_by_role("alert").wait_for()
        await a.reload()
        await saved(a)
        await a.get_by_role("button", name="生成视频", exact=True).click()
        await a.get_by_role("button", name="查询原提交", exact=True).click()
        await a.get_by_role("dialog").wait_for(state="detached")
        await saved(a)
        assert len(client.get(api_root + "/generation-tasks").json()) == before + 1
        checks.append(
            "lost successful generation response retries same request without duplicate task"
        )

        failure = "offline"
        await a.get_by_label("视频文案", exact=True).fill("断网后保留的编辑")
        await a.get_by_role("alert").filter(has_text="无法确认同步结果").wait_for()
        await a.reload()
        await a.get_by_role("button", name="恢复本机内容", exact=True).wait_for()
        failure = None
        await a.get_by_role("button", name="恢复本机内容", exact=True).click()
        await saved(a)
        assert (
            await a.get_by_label("视频文案", exact=True).input_value()
            == "断网后保留的编辑"
        )
        checks.append(
            "failed save retains scoped recovery across reload; "
            "explicit recovery persists successfully"
        )

        await a.get_by_role("button", name="文案版本", exact=True).click()
        await (
            a.get_by_role("dialog")
            .get_by_text("已确认版本", exact=True)
            .first.wait_for()
        )
        await a.get_by_role("button", name="关闭弹窗", exact=True).click()
        await a.get_by_role("button", name="音频驱动", exact=True).click()
        await a.locator('input[type="file"][accept="audio/*"]').set_input_files(
            {
                "name": "local-sample.wav",
                "mimeType": "audio/wav",
                "buffer": wav_fixture(),
            }
        )
        await saved(a)
        await a.reload()
        await a.get_by_text("音频已保存，可继续生成", exact=True).wait_for()
        assert not any("upload" in w["path"] for w in writes)
        checks.append(
            "version history remains available; media association "
            "survives reload with uploaded audio available across reload"
        )

        legacy = {
            "draft": {
                **project["content"]["draft"],
                "name": "旧浏览器草稿",
                "text": "旧草稿内容",
            },
            "copies": [
                {
                    "id": "old-copy",
                    "title": "旧文案",
                    "text": "旧文案正文",
                    "date": "2026-11-01",
                }
            ],
            "works": [
                {
                    "id": "old-work",
                    "draft": project["content"]["draft"],
                    "date": "2026-11-01",
                }
            ],
        }
        await b.evaluate(
            """value => localStorage.setItem(
              'polaris-video-studio-demo-v1', JSON.stringify(value))""",
            legacy,
        )
        await b.reload()
        await b.get_by_role("button", name="导入本机旧记录", exact=True).click()
        await saved(b)
        await b.get_by_role("button", name="导入本机旧记录", exact=True).wait_for(
            state="detached"
        )
        imported_count = len(client.get(api_root + "/projects").json())
        await b.reload()
        await saved(b)
        assert (
            await b.get_by_role("button", name="导入本机旧记录", exact=True).count()
            == 0
        )
        assert len(client.get(api_root + "/projects").json()) == imported_count
        assert await b.evaluate(
            "localStorage.getItem('polaris-video-studio-demo-v1') !== null"
        )
        assert any(
            v["snapshot"]["draft"]["text"] == "旧文案正文"
            for v in client.get(api_root + "/versions").json()
        )
        checks.append(
            "explicit legacy import preserves draft/library/demo "
            "records, keeps original backup and does not reimport after reload"
        )

        task = client.get(api_root + "/generation-tasks").json()[-1]
        assert task["snapshot"]["draft"]["text"] == "第一版口播文案"
        assert task["status"] == "completed"
        report = {
            "identity": "disposable external-auth fixtures, real FastAPI "
            "persistence with temporary SQLite; no real account login",
            "checks": checks,
            "project_count": len(client.get(api_root + "/projects").json()),
            "write_requests": len(writes),
            "paid_or_upload_calls": 0,
        }
        (output / "persistence-browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="video-persistence-") as directory:
        auth = FakeExternalAuthBackend(
            identity=verified_identity(email="1474953130@qq.com")
        )
        settings = external_settings(Path(directory)).model_copy(
            update={
                "video_providers_enabled": True,
                "video_media_dir": Path(directory) / "video",
            }
        )
        app = create_app(settings, auth)
        app.state.video_providers = FakeVideoProviders()
        with TestClient(app) as client:
            workspace = client.get("/api/v1/workspaces").json()[0]["id"]
            client.get(f"/api/v1/video-studio/workspaces/{workspace}/avatars")
            with app.state.session_factory() as session:
                session.get(VideoAvatarRecord, "qy-model-11").cover_path = str(
                    OWNED_IMAGE
                )
                session.commit()
            asyncio.run(verify(client))
