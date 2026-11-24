"""Staging-only boot wrapper: fake upstream providers with realistic latency.

Usage (inside a staging container): python -m stg_boot <module> [args...]
  e.g. python -m stg_boot uvicorn app.main:app --host 0.0.0.0 --port 8000
It patches, in-process and before the app is imported:
  * FakeXingheGateway.plan  -> +U(STG_PLAN_MIN, STG_PLAN_MAX) s   (planning, default 5-10 s)
  * FakeXingheGateway.edit / FakeProvider.execute -> +U(STG_IMAGE_MIN, STG_IMAGE_MAX) s (image, default 20-40 s)
  * build_tengli_gateway    -> offline replica planner (5-10 s), so no real HTTP gateway is built
  * VideoProviders          -> httpx.MockTransport fake vendor (submit 1-3 s, task runs STG_VIDEO_SECONDS)
No network request leaves the process for these paths, and no API key exists in staging.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import runpy
import sys
import time
from types import SimpleNamespace


def _rng(name: str, lo: float, hi: float) -> tuple[float, float]:
    return float(os.environ.get(name + "_MIN", lo)), float(os.environ.get(name + "_MAX", hi))


PLAN = _rng("STG_PLAN", 5, 10)
IMAGE = _rng("STG_IMAGE", 20, 40)
VIDEO_SECONDS = float(os.environ.get("STG_VIDEO_SECONDS", "60"))


def patch() -> None:
    from app import xinghe_agent as xa

    orig_plan, orig_edit = xa.FakeXingheGateway.plan, xa.FakeXingheGateway.edit

    async def plan(self, request):
        await asyncio.sleep(random.uniform(*PLAN))
        return await orig_plan(self, request)

    async def edit(self, request):
        if not getattr(request, "reconcile_only", False):
            await asyncio.sleep(random.uniform(*IMAGE))
        return await orig_edit(self, request)

    xa.FakeXingheGateway.plan = plan
    xa.FakeXingheGateway.edit = edit

    # Single-image job types (product_image, replica's remix route, ...) use the generic FakeProvider.
    from app import provider as prov

    orig_exec = prov.FakeProvider.execute

    async def execute(self, request):
        await asyncio.sleep(random.uniform(*IMAGE))
        return await orig_exec(self, request)

    prov.FakeProvider.execute = execute

    class StagingReplicaGateway:
        provider_name = "staging-fake"

        async def plan(self, request):
            await asyncio.sleep(random.uniform(*PLAN))
            return SimpleNamespace(
                payload={
                    "product_identity_lock": "preserve the uploaded product",
                    "reference_visual_analysis": "composition only",
                    "hard_composition_skeleton": "center",
                    "original_remix_prompt": "Product in the reference layout.",
                    "commercial_intent": "突出用户商品",
                },
                error_code=None,
                normalized_usage={"input_tokens": 20},
                actual_cost_micros=0,
            )

    xa.build_tengli_gateway = lambda *a, **k: StagingReplicaGateway()

    # Production opens video-studio to a single preview account. For load testing, staging opens it
    # to the synthetic @loadtest.invalid users only (str subclass makes `email != _PREVIEW_EMAIL` false).
    if os.environ.get("STG_VIDEO_GATE_OPEN") == "1":
        from app import video_studio_access as vsa

        class _LoadtestEmail(str):
            def __ne__(self, other):
                return not str(other).endswith("@loadtest.invalid")

            def __eq__(self, other):
                return str(other).endswith("@loadtest.invalid")

            __hash__ = str.__hash__

        vsa._PREVIEW_EMAIL = _LoadtestEmail(vsa._PREVIEW_EMAIL)

    try:
        import httpx
        from app import video_providers as vp
    except Exception:  # pragma: no cover - module layout differs
        return

    started: dict[str, float] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path == "/api/digital_human/models":
            return httpx.Response(200, json={"models": [{
                "id": 9001, "model_name": "压测数字人", "is_public": True, "is_active": True,
                "model_type": "video", "video_url": "https://quanyu.sowa.chat/staging-fake/9001.mp4"}]})
        if req.method == "GET" and path == "/api/tts/preset-voices":
            return httpx.Response(200, json={"voices": [{"id": "lt-voice-1", "name": "压测音色", "gender": "female"}]})
        if req.method == "POST":
            time.sleep(random.uniform(1, 3))
            tid = "stg_" + os.urandom(6).hex()
            started[tid] = time.time()
            return httpx.Response(200, json={"id": tid, "task_id": tid, "code": 0, "status": "queued"})
        tid = path.rstrip("/").rsplit("/", 1)[-1]
        age = time.time() - started.get(tid, time.time())
        done = age >= VIDEO_SECONDS
        return httpx.Response(200, json={
            "id": tid, "code": 0,
            "status": "failed" if done else "processing",
            "progress": min(99, int(age / VIDEO_SECONDS * 100)),
            "error": {"message": "staging fake vendor has no media"} if done else None,
        })

    orig_init = vp.VideoProviders.__init__

    def init(self, settings, transport=None):
        orig_init(self, settings, transport or httpx.MockTransport(handler))

    vp.VideoProviders.__init__ = init


def main() -> None:
    sys.path.insert(0, os.getcwd())
    patch()
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m stg_boot <module> [args...]")
    target = sys.argv[1]
    sys.argv = [target] + sys.argv[2:]
    runpy.run_module(target, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
