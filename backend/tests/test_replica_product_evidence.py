"""Original product context must reach initial and repair image calls."""

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.provider import ProviderOutcome
from app.replica_native import ReplicaInputTooLarge
from app.replica_native_provider import NativeReplicaProvider

from .test_replica_transport import run_at


def png(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 80), color).save(path, "PNG")
    return path


def setup(tmp_path, method, repair):
    original = png(tmp_path / "inputs/product-00.img", "blue")
    reference = png(tmp_path / "crops/screen-000.png", "red")
    anchor = png(tmp_path / "crops/product-anchor-00.png", "green")
    paths = [reference, anchor]
    if repair:
        paths.insert(0, png(tmp_path / "artwork/failed.png", "pink"))
    events = []

    async def edit(request):
        events.append(request)
        payload = BytesIO()
        Image.new("RGB", (64, 80), "white").save(payload, "PNG")
        return SimpleNamespace(
            outcome=ProviderOutcome.SUCCEEDED,
            artifact=SimpleNamespace(
                payload=payload.getvalue(), locally_resampled=False
            ),
            normalized_usage={"reported": False},
            actual_cost_micros=None,
            estimated_cost_micros=None,
            http_status=200,
            error_code=None,
            raw_usage={},
        )

    run = run_at(tmp_path, method, SimpleNamespace(edit=edit))
    provider = NativeReplicaProvider(None, run.gateway, None)

    async def save(*args, **kwargs):
        pass

    provider._save = save
    request = SimpleNamespace(
        workspace_id="ws_test",
        job_id="job_fixture",
        job_item_id="item_fixture",
        attempt_id="attempt_fixture",
    )

    async def render(extra=()):
        return await provider._render(
            run,
            request,
            {"token": "fixture"},
            "Native prompt remains unchanged",
            paths + list(extra),
            [64, 80],
            "M001",
        )

    return render, events, original, paths, tmp_path


@pytest.mark.parametrize("method", ["exact", "style"])
@pytest.mark.parametrize("repair", [False, True])
def test_original_context_reaches_both_modes_without_changing_native_source_order(
    tmp_path, method, repair
):
    render, events, original, paths, _ = setup(tmp_path, method, repair)
    before = original.read_bytes()
    result = asyncio.run(render())
    assert result.exists() and len(events) == 1
    request = events[0]
    assert [s.filename for s in request.sources] == [p.name for p in paths] + [
        original.name
    ]
    assert request.sources[-1].payload == before == original.read_bytes()
    assert request.sources[-1].source_role == "product_reference"
    assert request.prompt == "Native prompt remains unchanged"
    assert asyncio.run(render()) == result
    assert len(events) == 1  # Cached artwork never dispatches again.


def test_original_already_in_native_inputs_is_not_duplicated(tmp_path):
    render, events, original, _, _ = setup(tmp_path, "exact", False)
    asyncio.run(render([original]))
    assert sum(s.filename == original.name for s in events[0].sources) == 1


def test_original_context_over_budget_does_not_consume_generation_token(
    tmp_path, monkeypatch
):
    render, events, original, paths, root = setup(tmp_path, "exact", False)
    # Native crop inputs fit; adding the original must be checked before dispatch.
    measured = sum(len(p.read_bytes()) for p in paths)
    assert measured < measured + len(original.read_bytes())
    monkeypatch.setattr("app.replica_native.MAX_SOURCE_BYTES", measured)
    with pytest.raises(ReplicaInputTooLarge):
        asyncio.run(render())
    assert events == []
    assert not (root / "invocations.json").exists()
