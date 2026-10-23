"""Structural native handoff tests; synthetic pixels do not prove visual quality."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.provider import ProviderOutcome
from app.replica_native import ReplicaNativeError, read_json, write_json
from app.replica_native_provider import NativeReplicaProvider

from .test_replica_product_evidence import png
from .test_replica_transport import run_at


def test_real_exact_repair_handoff_binds_second_image_as_blueprint(tmp_path):
    original = png(tmp_path / "inputs/product-00.img", "blue")
    anchor = png(tmp_path / "crops/product-anchor-00.png", "green")
    reference = png(tmp_path / "crops/screen-00.png", "red")
    draft = png(tmp_path / "artwork/draft.png", "pink")
    calls = []

    async def edit(request):
        calls.append(request)
        return SimpleNamespace(
            outcome=ProviderOutcome.SUCCEEDED,
            artifact=SimpleNamespace(
                payload=draft.read_bytes(), locally_resampled=False
            ),
            normalized_usage={"reported": False},
            actual_cost_micros=None,
            estimated_cost_micros=None,
            http_status=200,
            error_code=None,
            raw_usage={},
        )

    run = run_at(tmp_path, "exact", SimpleNamespace(edit=edit))
    module = {
        "id": "M01",
        "reference_unit_id": "R01",
        "reference_path": str(reference),
        "output_canvas": {"width": 64, "height": 80},
        "visual_contract": {},
        "page_duty": "Synthetic fixture duty",
        "buyer_conclusion": "Fixture conclusion",
        "generation_brief": "Synthetic fixture brief",
        "copy_units": [],
    }
    write_json(
        tmp_path / "session.json",
        {
            "runtime_version": "6.0.0",
            "state": "REPAIR_PREPARED",
            "module_index": 0,
            "input": {"product_images": [str(anchor)]},
            "plan": {
                "modules": [module],
                "sequence_contract": {"source_unit_order": ["R01"]},
            },
            "modules": [
                {
                    "id": "M01",
                    "status": "PENDING",
                    "attempts": [{"artwork": str(draft)}],
                }
            ],
            "current": {
                "repair_plan": {
                    "material_failures": ["Fixture face mismatch"],
                    "single_edit_instruction": "Fix only the synthetic face region",
                }
            },
        },
    )
    run.cli(
        "generate-next",
        session=tmp_path / "session.json",
        out=tmp_path / "request.json",
    )
    native = read_json(tmp_path / "request.json")
    assert native["mode"] == "REPAIR"
    assert native["reference_images"][:2] == [str(draft), str(reference)]
    provider = NativeReplicaProvider(None, run.gateway, None)

    async def save(*args, **kwargs):
        pass

    provider._save = save
    request = SimpleNamespace(
        workspace_id="fixture",
        job_id="fixture",
        job_item_id="fixture",
        attempt_id="fixture",
    )
    asyncio.run(
        provider._render(
            run,
            request,
            native,
            native["prompt"],
            [Path(p) for p in native["reference_images"]],
            [64, 80],
            "M01",
        )
    )
    sent = calls[0]
    assert sent.prompt.startswith(native["prompt"] + "\n\nIMAGE_BINDINGS=")
    assert "composition blueprint at attached image 2" in sent.prompt
    assert [s.filename for s in sent.sources] == [
        draft.name,
        reference.name,
        anchor.name,
        original.name,
    ]
    bindings = json.loads(sent.prompt.split("IMAGE_BINDINGS=", 1)[1].splitlines()[0])
    assert [b["role"] for b in bindings] == [
        "current_artwork",
        "composition_reference",
        "product_detail",
        "product_original",
    ]


@pytest.mark.parametrize("paths", [[], ["draft"]])
def test_exact_repair_without_canvas_or_blueprint_does_not_consume_token(
    tmp_path, paths
):
    draft = png(tmp_path / "artwork/draft.png", "pink")
    run = run_at(tmp_path, "exact")
    provider = NativeReplicaProvider(None, None, None)
    request = SimpleNamespace(
        workspace_id="fixture",
        job_id="fixture",
        job_item_id="fixture",
        attempt_id="fixture",
    )
    with pytest.raises(ReplicaNativeError):
        asyncio.run(
            provider._render(
                run,
                request,
                {"token": "unspent", "mode": "REPAIR"},
                "Fixture native prompt",
                [draft for _ in paths],
                [64, 80],
                "M01",
            )
        )
    assert not (tmp_path / "invocations.json").exists()
