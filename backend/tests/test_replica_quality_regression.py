"""Content fidelity survives early completion and parallel image generation."""

import asyncio
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

from app.replica_completion import PLAN, prepare, prompt
from app.replica_direct_delivery import V8_BINDING, V9_BINDING, execute
from app.replica_exact_compact import run_class
from app.replica_native import ReplicaSegmentationInvalid, read_json, write_json
from app.replica_native_provider import NativeReplicaProvider
from tests.test_replica_compact import SyntheticGateway, setup_run


def test_old_content_protocols_remain_byte_frozen():
    for binding in (V8_BINDING, V9_BINDING):
        cls = run_class("exact", binding)
        assert sys.modules[cls.__module__].protocol_binding() == binding


def test_complete_marketing_visual_keeps_full_native_planning(tmp_path):
    gateway = SyntheticGateway()
    original = gateway.plan

    async def observe(request):
        response = await original(request)
        if json.loads(request.product_information[0])["stage"] == "intake":
            response.payload["route"] = "MARKETING_VISUAL_SET"
        return response

    gateway.plan = observe
    run, _, payload, records = setup_run(tmp_path, gateway)
    result = asyncio.run(run.prepare(payload, records))
    assert len(result) == 1
    assert run.state()["state"] == "READY"
    assert run.state()["plan"]["modules"][0]["visual_contract"]
    stages = [json.loads(r.product_information[0])["stage"] for r in gateway.requests]
    assert "screen_split" not in stages and "screen_inventory" not in stages
    assert "layout" in stages and "plan" in stages and "review_plan" in stages
    assert not (run.root / PLAN).exists()


def test_completion_retains_the_native_prompt_when_a_plan_exists(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    original = deepcopy(run.state())
    calls = len(gateway.requests)
    asyncio.run(prepare(run, payload, records, ReplicaSegmentationInvalid()))
    plan = read_json(run.root / PLAN)
    for index, unit in enumerate(plan["units"]):
        compiled = prompt(plan, unit, index)
        assert "AI-observed reference facts:" in compiled
        assert "Approved visible copy only:" in compiled
        assert "Reproduce subject scale, layout" in compiled
        assert unit["proposal"] == original["plan"]["modules"][index]
    assert run.state() == original
    assert len(gateway.requests) == calls


def test_early_completion_uses_strict_pixels_instead_of_generic_hero(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    (run.root / "session.json").unlink()
    calls = len(gateway.requests)
    asyncio.run(prepare(run, payload, records, ReplicaSegmentationInvalid()))
    plan = read_json(run.root / PLAN)
    compiled = prompt(plan, plan["units"][0], 0)
    assert "binding composition blueprint" in compiled
    assert "background palette" in compiled
    assert "Do not recolor the background" in compiled
    assert "text locations and size tiers" in compiled
    assert "source_pixels_only" in compiled
    assert plan["resolved_facts"] == run.context["resolved_facts"]
    assert len(gateway.requests) == calls  # No extra paid analysis or fake audit.


def test_concurrent_requests_keep_their_own_fact_adaptations(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    state = run.state()
    for module in state["plan"]["modules"]:
        module["fact_adaptations"] = [{"current_module": module["id"]}]
        module["commercial_adaptation"]["supported_role"] = module["id"]
    write_json(run.run / "session.json", state)
    provider = NativeReplicaProvider(None, gateway, run.storage, max_concurrency=2)

    async def checkpoint(*args, **kwargs):
        # Force another module to advance the shared progress cursor before
        # this module compiles its actual image request.
        await asyncio.sleep(0)

    provider._save = checkpoint
    request = SimpleNamespace(
        workspace_id="ws_test",
        job_id="job_parallel",
        job_item_id="item_parallel",
        attempt_id="attempt_parallel",
    )
    outputs = asyncio.run(execute(provider, run, request))
    assert len(outputs) == 2
    assert len(gateway.image_requests) == 2
    for image_request in gateway.image_requests:
        module_id = image_request.group_key
        adaptations = image_request.prompt.split("FACT_ADAPTATIONS=", 1)[1].split(
            "\nCOMMERCIAL_ADAPTATION=", 1
        )[0]
        assert json.loads(adaptations) == [{"current_module": module_id}]
