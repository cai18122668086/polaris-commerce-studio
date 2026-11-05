"""Render the actual vendor catalogue through a disposable authenticated fixture.

Only vendor GETs and media downloads are permitted; no paid submissions.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.main import create_app
from app.video_providers import VideoProviders
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)


class ReadOnlyProviders(VideoProviders):
    def request(self, vendor, method, path, **kwargs):
        assert method == "GET", "This UI validation must never submit paid work"
        return super().request(vendor, method, path, **kwargs)


async def verify(client):
    workspace = client.get("/api/v1/workspaces").json()[0]["id"]
    root = f"/api/v1/video-studio/workspaces/{workspace}"
    avatars = client.get(root + "/avatars").json()
    public = [a for a in avatars if a["source"] == "quanyu_public"]
    assert len(public) >= 40
    owned = next(a for a in avatars if a["source"] == "self_owned")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route_api(route):
            req = route.request
            path = urlparse(req.url).path
            assert req.method == "GET", "Read-only UI validation"
            if path.startswith("/api/v1/video-studio") or path in {
                "/api/v1/me",
                "/api/v1/workspaces",
            }:
                response = await asyncio.to_thread(client.get, path)
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

        await page.route("**/api/v1/**", route_api)
        await page.goto(
            os.environ.get("VIDEO_STUDIO_ORIGIN", "http://127.0.0.1:3000")
            + "/video-studio/avatars"
        )
        await page.get_by_role("button", name="公共模特", exact=True).click()
        await page.get_by_role("button", name="使用", exact=True).first.wait_for()
        await page.wait_for_function(
            "Array.from(document.querySelectorAll('img[alt$=\"数字人形象\"]')).filter(i=>i.complete && i.naturalWidth > 100).length >= 12",
            timeout=120000,
        )
        output = ROOT / "outputs/video-studio"
        await page.screenshot(
            path=str(output / "public-library-real-media-fixture.png"), full_page=True
        )
        await page.get_by_role("button", name="我的定制", exact=True).click()
        await page.get_by_text(owned["name"], exact=True).first.wait_for()
        await page.wait_for_function(
            "Array.from(document.querySelectorAll('img[alt$=\"数字人形象\"]')).some(i=>i.complete && i.naturalWidth > 100)"
        )
        await page.screenshot(
            path=str(output / "owned-library-real-media-fixture.png"), full_page=True
        )
        assert not errors, errors
        report = {
            "identity": "disposable external-auth fixture; vendor catalogue and media are real; no real user login",
            "public_video_models": len(public),
            "owned_reference_images": 1,
            "vendor_paid_submissions": 0,
            "browser_errors": errors,
            "checks": [
                "real public covers replace stock photos",
                "private provider models excluded",
                "built-in generated reference appears under owned library",
                "existing desktop layout renders",
            ],
        }
        (output / "real-library-browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        await browser.close()


if __name__ == "__main__":
    real = Settings(_env_file=ROOT / "backend/.env")
    with tempfile.TemporaryDirectory(prefix="video-real-media-") as directory:
        settings = external_settings(Path(directory)).model_copy(
            update={
                "video_providers_enabled": True,
                "video_media_dir": real.video_media_dir,
            }
        )
        auth = FakeExternalAuthBackend(
            identity=verified_identity(email="1474953130@qq.com")
        )
        app = create_app(settings, auth)
        app.state.video_providers = ReadOnlyProviders(real)
        with TestClient(app) as client:
            asyncio.run(verify(client))
