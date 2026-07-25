from __future__ import annotations

import argparse
import time
from io import BytesIO
from typing import Any

import httpx2
from PIL import Image


def _image_payload() -> bytes:
    output = BytesIO()
    Image.new("RGB", (96, 96), (42, 118, 246)).save(output, format="PNG")
    return output.getvalue()


def run(base_url: str) -> dict[str, Any]:
    workspace_id = f"smoke-{int(time.time())}"
    with httpx2.Client(
        base_url=base_url,
        timeout=10,
        trust_env=False,
    ) as client:
        health = client.get("/health")
        health.raise_for_status()

        upload = client.post(
            "/api/assets",
            data={"workspace_id": workspace_id, "origin": "upload"},
            files={"file": ("smoke.png", _image_payload(), "image/png")},
        )
        upload.raise_for_status()
        asset = upload.json()

        created = client.post(
            "/api/jobs",
            json={
                "type": "local_edit",
                "workspace_id": workspace_id,
                "input_asset_ids": [asset["id"]],
                "configuration": {"quality": "balanced"},
                "estimated_cost": 0,
            },
        )
        created.raise_for_status()
        job = created.json()

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = client.get(f"/api/jobs/{job['id']}")
            response.raise_for_status()
            job = response.json()
            if job["status"] in {"completed", "partial", "failed", "cancelled"}:
                break
            time.sleep(0.25)

    if job["status"] != "completed":
        raise RuntimeError(f"job did not complete successfully: {job}")
    if not job["queue_task_id"]:
        raise RuntimeError("Celery task id was not persisted")
    if job["api_request_count"] != 0 or job["actual_cost"] != 0:
        raise RuntimeError("mock runner unexpectedly reported paid API usage")
    return {
        "health": health.json(),
        "asset_id": asset["id"],
        "storage_key": asset["storage_key"],
        "job_id": job["id"],
        "queue_task_id": job["queue_task_id"],
        "status": job["status"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()
    print(run(arguments.base_url))
