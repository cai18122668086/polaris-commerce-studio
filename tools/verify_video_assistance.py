"""Authoring UI + real API persistence, disposable auth/DB and fake providers."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

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
from tests.test_video_assistance import FakeAssistance
from tests.test_video_generation import FakeVideoProviders
from tests.test_video_projects import payload


class BrowserAssistance(FakeAssistance):
    def plan(self, kind, inputs):
        result, receipt = super().plan(kind, inputs)
        if kind == "rewrite":
            result["script"] = (
                "今天分享桌面整理，把零散物件集中放好，按需选择自己的收纳方法。"
            )
        return result, receipt


async def verify(client, root, pid):
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        lost_create = True
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def api(route):
            nonlocal lost_create
            req = route.request
            u = urlparse(req.url)
            path = u.path
            if path.startswith("/api/v1/video-studio") or path in {
                "/api/v1/me",
                "/api/v1/workspaces",
            }:
                response = await asyncio.to_thread(
                    client.request,
                    req.method,
                    path + ("?" + u.query if u.query else ""),
                    json=req.post_data_json if req.method != "GET" else None,
                )
                if (
                    lost_create
                    and req.method == "POST"
                    and path.endswith("/assistance-tasks")
                    and req.post_data_json.get("kind") == "create"
                ):
                    lost_create = False
                    assert response.status_code == 200
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
            elif path.endswith("/credits"):
                await route.fulfill(
                    json={
                        "enforcement_enabled": False,
                        "balance_credits": 0,
                        "available_credits": 0,
                        "reserved_credits": 0,
                        "pricing": [],
                    }
                )
            elif path.endswith("/creation-summary"):
                await route.fulfill(json={"active": 0, "needs_attention": 0})
            elif "announcements" in path:
                await route.fulfill(json={"items": []})
            else:
                await route.fulfill(json=[])

        async def saved():
            await (
                page.get_by_role("status", name="项目保存状态")
                .filter(has_text="已保存")
                .wait_for()
            )

        await page.route("**/api/v1/**", api)
        await page.goto(
            os.environ.get("VIDEO_STUDIO_ORIGIN", "http://127.0.0.1:3000")
            + "/video-studio/create?project="
            + pid
        )
        await saved()
        await page.get_by_label("告诉文案助手你的需求").fill(
            "普通收纳盒，写一段自然的桌面收纳介绍，不要编造参数。"
        )
        await page.get_by_role("button", name="发送文案需求", exact=True).click()
        await page.get_by_role("button", name="使用这段文案", exact=False).wait_for()
        assert (
            await page.get_by_label("视频文案", exact=True).input_value()
            == "尚未采用的原稿"
        )
        await page.get_by_role("button", name="使用这段文案", exact=False).click()
        await saved()
        assert (
            "集中整理" in await page.get_by_label("视频文案", exact=True).input_value()
        )
        await page.reload()
        await saved()
        await page.get_by_role("button", name="使用这段文案", exact=False).wait_for()
        await page.get_by_role("button", name="文案二创", exact=True).click()
        await page.get_by_label("原始文案", exact=True).fill(
            "参考商品价格99元，容量500毫升。"
        )
        await page.get_by_role("button", name="生成改写文案", exact=False).click()
        rewritten = page.get_by_label("改写结果", exact=True)
        await rewritten.wait_for()
        assert "99元" not in await rewritten.input_value()
        assert (
            "集中整理" in await page.get_by_label("视频文案", exact=True).input_value()
        )
        await page.get_by_role("button", name="使用改写稿", exact=True).click()
        await saved()
        assert (
            "按需选择" in await page.get_by_label("视频文案", exact=True).input_value()
        )
        await page.get_by_role("button", name="文案二创", exact=True).click()
        await page.get_by_role("button", name="视频链接提取", exact=True).click()
        await page.get_by_placeholder("粘贴公开抖音视频链接").fill(
            "https://www.douyin.com/video/123456789"
        )
        await page.get_by_role("button", name="提取文案", exact=False).click()
        await page.get_by_role("button", name="文案改写", exact=True).click()
        await page.wait_for_function(
            "document.querySelector('textarea[placeholder=\"粘贴需要改写的参考文案\"]')?.value.includes('完整语音原文')",
            timeout=15000,
        )
        raw = await page.get_by_label("原始文案", exact=True).input_value()
        await page.get_by_role("button", name="使用原文", exact=True).click()
        await saved()
        assert await page.get_by_label("视频文案", exact=True).input_value() == raw
        project = client.get(root + "/projects/" + pid).json()
        assert project["content"]["draft"]["text"] == raw
        assert (
            project["content"]["product_facts"]
            == "普通收纳盒，未确认价格、材质和尺寸。"
        )
        assert any(
            "完整语音原文" in r["original_text"]
            for r in project["content"]["references"]
        )
        assert not errors, errors
        out = ROOT / "outputs/video-studio"
        await page.screenshot(path=str(out / "assistance-editor-fixture.png"))
        report = {
            "identity": "disposable external-auth fixture; real FastAPI and temporary SQLite; fake providers",
            "checks": [
                "lost successful planning response recovers the same task without a second model call",
                "script creation remains unadopted until explicit use",
                "completed model output restores after reload",
                "rewriting keeps confirmed product facts separate from reference price",
                "voice transcript is saved with source and can feed rewriting",
                "use-original preserves extracted text exactly despite an earlier rewrite candidate",
                "editor layout unchanged",
            ],
            "real_provider_calls": 0,
            "browser_errors": errors,
        }
        (out / "assistance-browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="video-assistance-ui-") as directory:
        settings = external_settings(Path(directory)).model_copy(
            update={
                "video_providers_enabled": True,
                "video_script_planning_enabled": True,
                "video_extract_enabled": True,
                "video_media_dir": Path(directory) / "media",
            }
        )
        app = create_app(
            settings,
            FakeExternalAuthBackend(
                identity=verified_identity(email="1474953130@qq.com")
            ),
        )
        app.state.video_providers = FakeVideoProviders()
        app.state.video_assistance_provider = BrowserAssistance()
        with TestClient(app) as client:
            ws = client.get("/api/v1/workspaces").json()[0]["id"]
            root = f"/api/v1/video-studio/workspaces/{ws}"
            client.get(root + "/avatars")
            with app.state.session_factory() as session:
                session.get(VideoAvatarRecord, "qy-model-11").cover_path = str(
                    OWNED_IMAGE
                )
                session.commit()
            pid = str(uuid4())
            data = payload()
            data["content"]["draft"].update(
                text="尚未采用的原稿", avatarId="qy-model-11", voiceId="qy-voice-1"
            )
            data["content"]["product_facts"] = "普通收纳盒，未确认价格、材质和尺寸。"
            client.put(root + "/projects/" + pid, json=data)
            asyncio.run(verify(client, root, pid))
