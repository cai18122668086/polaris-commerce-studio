from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.aurora_main_image_provider as provider_module
from app.aurora_main_image_planner import AuroraPlanningError
from app.aurora_main_image_provider import AuroraMainImageProvider
from app.provider import ProviderArtifact, ProviderRequest


@pytest.mark.parametrize("state", ["slow_success", "stalled", "failed", "cancelled"])
def test_style_wait_preserves_slow_accepted_reference_and_bounded_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    elapsed = [0.0]
    calls = []
    workspace = tmp_path / "job_style" / "parallel-v20" / "page-02" / "attempt-two"
    workspace.mkdir(parents=True)
    reference_root = workspace.parent.parent / "page-01" / "attempt-one"
    reference_root.mkdir(parents=True)
    reference = reference_root / "accepted.png"
    reference.write_bytes(b"accepted-page-zero-pixels")
    candidate = workspace / "candidate.png"
    candidate.write_bytes(b"retained-page-one-pixels")

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, query):
            return state if state in {"failed", "cancelled"} else "running"

    async def sleep(seconds):
        elapsed[0] += 60
        if state == "slow_success" and elapsed[0] >= 240:
            (reference_root / "session.json").write_text(
                json.dumps(
                    {
                        "accepted_pages": [0],
                        "search_calibrated": True,
                        "generated_versions": [
                            {
                                "page_index": 0,
                                "status": "ACCEPTED",
                                "file": str(reference),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

    async def plan(request):
        calls.append(request)
        return SimpleNamespace(
            error_code=None,
            payload={"agent_pixel_reviewed": True},
            normalized_usage={},
            actual_cost_micros=0,
        )

    monkeypatch.setattr(provider_module, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(provider_module.asyncio, "sleep", sleep)
    provider = AuroraMainImageProvider(
        Database, SimpleNamespace(plan=plan), None, work_root=tmp_path
    )
    request = ProviderRequest(
        workspace_id="workspace",
        job_id="job_style",
        job_item_id="page_one",
        attempt_id="attempt_two",
        operation="domestic_main_image",
        idempotency_key="retained-style",
        configuration={"item": {}},
    )
    data = candidate.read_bytes()
    artifact = ProviderArtifact(
        payload=data,
        filename=candidate.name,
        content_type="image/png",
        width=1024,
        height=1024,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    if state == "slow_success":
        result = asyncio.run(
            provider._calibrate_parallel_style(request, workspace, candidate, artifact)
        )
        assert result[0]["agent_pixel_reviewed"] is True
        assert elapsed[0] == 240
        assert len(calls) == 1
        assert [source.payload for source in calls[0].sources] == [
            reference.read_bytes(),
            data,
        ]
    else:
        with pytest.raises(AuroraPlanningError, match="page 0"):
            asyncio.run(
                provider._calibrate_parallel_style(
                    request, workspace, candidate, artifact
                )
            )
        assert not calls
        assert elapsed[0] == (600 if state == "stalled" else 0)
    assert candidate.read_bytes() == data
