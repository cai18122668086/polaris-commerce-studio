"""Local browser regression with disposable external-auth fixtures, never real login.

Run from repo root with backend dev + browser dependencies installed:
  .venv/Scripts/python.exe tools/verify_video_studio_access.py
Requires the local frontend at VIDEO_STUDIO_ORIGIN (default http://127.0.0.1:3000).
All API calls are intercepted; the access response runs the actual FastAPI gate.
"""

import asyncio
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app
from fastapi.testclient import TestClient
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)

ORIGIN = os.environ.get("VIDEO_STUDIO_ORIGIN", "http://127.0.0.1:3000")
SCREENS = ["", "/create", "/avatars", "/voices", "/library", "/works", "/editing"]
STUDIO = '[aria-label="视频空间导航"], [aria-label="视频编辑器"]'
EMAIL = "1474953130@qq.com"


async def verify(client, backend):
    mode = "backend"
    writes = []
    checks = []
    access_calls = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})

        async def api(route):
            nonlocal access_calls
            path = urlparse(route.request.url).path
            if route.request.method != "GET":
                writes.append(path)
                await route.fulfill(status=405, json={})
                return
            if path == "/api/v1/video-studio/access":
                access_calls += 1
                result = client.get(
                    path, headers={"X-User-Email": EMAIL, "X-User-Id": EMAIL}
                )
                status, body = result.status_code, result.json()
                if mode in ["slow", "late"]:
                    await asyncio.sleep(9 if mode == "slow" else 1)
                elif mode == "outage":
                    status, body = 503, {"error": {"code": "UNAVAILABLE"}}
                elif mode == "malformed":
                    status, body = 200, {"allowed": "true", "user_id": "fixture"}
                elif mode == "network":
                    await route.abort()
                    return
                # A canceled stale/timeout request cannot restore a grant.
                with suppress(PlaywrightError):
                    await route.fulfill(
                        status=status,
                        json=body,
                        headers={"Cache-Control": "private, no-store"},
                    )
                return
            if path == "/api/v1/me":
                result = client.get(path)
                await route.fulfill(status=result.status_code, json=result.json())
                return
            if path.endswith("/avatars"):
                await route.fulfill(
                    json=[
                        {
                            "id": "fixture-public",
                            "name": "权限夹具公共形象",
                            "source": "quanyu_public",
                            "gender": "女",
                            "tag": "公共数字人",
                            "cover_url": "/polaris-mark.svg",
                            "preview_url": None,
                            "ready": True,
                        }
                    ]
                )
                return
            if path.endswith("/voices"):
                await route.fulfill(
                    json=[
                        {
                            "id": "qy-voice-1",
                            "name": "温柔女声",
                            "gender": "女",
                            "tag": "公共音色",
                            "description": "权限夹具",
                        }
                    ]
                )
                return
            if path == "/api/v1/workspaces":
                body = [
                    {
                        "id": "ws-video-browser-fixture",
                        "name": "Fixture",
                        "role": "owner",
                    }
                ]
            elif path.endswith("/credits"):
                body = {
                    "enforcement_enabled": False,
                    "balance_credits": 0,
                    "available_credits": 0,
                    "reserved_credits": 0,
                    "pricing": [],
                }
            elif path.endswith("/creation-summary"):
                body = {"active": 0, "needs_attention": 0}
            elif path.endswith("/runtime"):
                body = {"capabilities": {"features": {}}}
            elif path.endswith("/processing-consent"):
                body = {"accepted": True}
            elif "announcements" in path:
                body = {"items": []}
            else:
                body = []
            await route.fulfill(json=body)

        await context.route("**/api/v1/**", api)
        await context.add_init_script("""window.__studioSeen = false;
          new MutationObserver(() => {
            if (document.querySelector(
              '[aria-label="视频空间导航"], [aria-label="视频编辑器"]'))
              window.__studioSeen = true;
          }).observe(document, {childList:true, subtree:true});
          localStorage.setItem('videoStudioAllowed', 'true');
          localStorage.setItem('email', '1474953130@qq.com');
        """)
        page = await context.new_page()

        async def open_screen(screen, allowed):
            await page.goto(
                ORIGIN + "/video-studio" + screen + "?allowed=true&email=" + EMAIL
            )
            if allowed:
                await page.locator(STUDIO).first.wait_for()
            else:
                await page.get_by_role("heading", name="页面暂不可用").wait_for()
                await page.wait_for_timeout(250)
                assert await page.locator(STUDIO).count() == 0
                assert await page.evaluate("window.__studioSeen") is False

        backend.identity = verified_identity(email="ordinary@example.com")
        for screen in SCREENS:
            await open_screen(screen, False)
        checks.append(
            "ordinary account: all 7 direct routes denied, no workbench flash; "
            "storage/query spoof ignored"
        )
        output = ROOT / "outputs" / "video-studio"
        output.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output / "gray-denied.png"))

        async def check_entries(allowed):
            await page.set_viewport_size({"width": 1440, "height": 1000})
            await page.goto(ORIGIN)
            await page.locator("nav.main-nav").wait_for()
            if allowed:
                await page.locator('nav.main-nav a[href="/video-studio"]').wait_for()
                assert (
                    await page.locator(
                        'nav.main-nav a[href="/video-studio"]'
                    ).get_attribute("target")
                    == "_blank"
                )
            else:
                await page.wait_for_timeout(300)
                assert await page.locator('a[href="/video-studio"]').count() == 0
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.get_by_role("button", name="打开主导航", exact=True).click()
            link = page.locator('#mobile-primary-navigation a[href="/video-studio"]')
            if allowed:
                await link.wait_for(state="visible")
                assert await link.get_attribute("target") == "_blank"
                async with context.expect_page() as popup:
                    await link.click()
                tab = await popup.value
                await tab.locator(STUDIO).first.wait_for()
                await tab.close()
            else:
                assert await link.count() == 0

        await check_entries(False)
        checks.append("ordinary desktop + mobile entries hidden")
        backend.identity = verified_identity(email=EMAIL)
        await check_entries(True)
        checks.append(
            "verified fixture desktop + mobile entries visible; new-tab access allowed"
        )
        await page.set_viewport_size({"width": 1440, "height": 1000})
        for screen in SCREENS:
            await open_screen(screen, True)
        await page.screenshot(path=str(output / "gray-allowed-fixture.png"))
        checks.append("verified external fixture: all 7 routes accessible")

        for failure in ["outage", "malformed", "network", "slow"]:
            mode = failure
            await open_screen("/create", False)
            await page.wait_for_timeout(9500 if failure == "slow" else 400)
            assert await page.locator(STUDIO).count() == 0
            assert await page.evaluate("window.__studioSeen") is False
        checks.append(
            "503, malformed response, network failure, 9s late success "
            "all denied; no flash"
        )

        mode = "backend"
        await open_screen("/create", True)
        sender = await context.new_page()
        await sender.goto(ORIGIN + "/legal/terms")

        async def broadcast(value):
            await sender.evaluate(
                """value => {
                  const c = new BroadcastChannel('polaris-auth-lifecycle');
                  c.postMessage(value); setTimeout(() => c.close(), 100);
                }""",
                value,
            )

        await broadcast("revoke")
        await page.locator(STUDIO).first.wait_for(state="detached")
        await page.evaluate("dispatchEvent(new Event('focus'))")
        await page.wait_for_timeout(250)
        assert await page.locator(STUDIO).count() == 0
        backend.identity = verified_identity(email="other@example.com")
        await broadcast("changed")
        await page.wait_for_timeout(300)
        assert await page.locator(STUDIO).count() == 0
        backend.identity = verified_identity(email=EMAIL)
        await broadcast("changed")
        await page.locator(STUDIO).first.wait_for()
        mode = "late"
        await page.evaluate("dispatchEvent(new Event('focus'))")
        await page.wait_for_timeout(100)
        await broadcast("revoke")
        await page.wait_for_timeout(1300)
        assert await page.locator(STUDIO).count() == 0
        checks.append(
            "cross-tab signout + account switch + focus cannot retain grant; "
            "late response after revoke ignored"
        )
        await sender.close()

        mode = "backend"
        from app.supertokens_auth import ExternalIdentity

        for identity in [
            None,
            verified_identity(email=""),
            ExternalIdentity("unverified", "unverified", EMAIL, False),
        ]:
            backend.identity = identity
            await open_screen("/create", False)
            await check_entries(False)
        checks.append(
            "missing session, empty/unverified email: route + both entries denied"
        )

        # An entirely separate context makes real, unmocked requests to the local
        # development server. It must not receive the fixture's grant.
        live = await browser.new_context(viewport={"width": 1440, "height": 1000})
        live_page = await live.new_page()
        for screen in SCREENS:
            await live_page.goto(ORIGIN + "/video-studio" + screen)
            await live_page.get_by_role("heading", name="页面暂不可用").wait_for()
            assert await live_page.locator(STUDIO).count() == 0
        await live_page.screenshot(path=str(output / "gray-live-denied.png"))
        await live_page.goto(ORIGIN)
        await live_page.locator("nav.main-nav").wait_for()
        await live_page.wait_for_timeout(500)
        assert await live_page.locator('a[href="/video-studio"]').count() == 0
        await live.close()
        checks.append(
            "unmocked local development identity: all 7 routes + desktop entry denied"
        )
        assert not writes, writes
        assert access_calls > 20
        report = {
            "identity": "disposable external-auth fixtures; no real account login",
            "checks": checks,
            "access_requests": access_calls,
            "api_writes": writes,
        }
        (output / "gray-browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="video-gray-") as directory:
        backend = FakeExternalAuthBackend()
        with TestClient(
            create_app(external_settings(Path(directory)), backend)
        ) as client:
            asyncio.run(verify(client, backend))
