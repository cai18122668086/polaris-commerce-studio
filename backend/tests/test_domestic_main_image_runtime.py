from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.domestic_main_image_runtime import HarnessAdapter, default_frozen_package


def _source_image(path: Path) -> None:
    image = Image.new("RGB", (1024, 1024), "#efe7d8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((220, 160, 804, 864), radius=72, fill="#d84d32")
    draw.rectangle((390, 245, 635, 765), fill="#f6f1e8")
    image.save(path, format="PNG")


def _raw(image_path: Path) -> dict[str, object]:
    return {
        "request_id": "fixture-main-image-v2",
        "profile01_semantics_read": False,
        "product": {
            "name": "桌面循环扇",
            "category": "小家电",
            "original_references": [
                {
                    "evidence_id": "evidence-01",
                    "path": str(image_path),
                    "role": "PRODUCT_IDENTITY_AUTHORITY",
                    "source_role": "primary",
                }
            ],
            "verified_attributes": {"额定电压": "5V", "颜色": "红白"},
            "verified_selling_points": [
                "三档风速",
                "上下角度可调",
                "可拆洗前网罩",
                "USB-C 供电",
                "桌面小体积",
                "红白双色机身",
            ],
            "verified_scenes": ["办公桌", "床头柜"],
            "verified_offers": [],
            "verified_service_or_trust_facts": ["额定电压 5V"],
        },
    }


def _identity(image_path: Path) -> dict[str, object]:
    return {
        "request_id": "fixture-main-image-v2",
        "product_form": "圆角矩形底座连接圆形扇头的桌面循环扇",
        "identity_summary": "红色外框、白色扇叶区域、单个底座与单个扇头",
        "evidence": [
            {
                "evidence_id": "evidence-01",
                "path": str(image_path),
                "view_tags": ["FRONT", "primary"],
            }
        ],
        "must_preserve": [
            "单个圆形扇头与单个圆角矩形底座的连接关系",
            "红色外框与白色中心的色块关系",
        ],
        "must_not_change": ["不得增加第二个扇头", "不得改变红白配色"],
        "previous_generated_images_used": False,
        "profile01_semantics_read": False,
    }


def _compile(adapter: HarnessAdapter, image_path: Path) -> dict[str, object]:
    started = adapter.run(
        "start", session=None, json_arguments={"input": _raw(image_path)}
    )
    assert started.exit_code == 0
    assert started.session is not None
    locked = adapter.run(
        "lock-identity",
        session=started.session,
        json_arguments={"identity": _identity(image_path)},
    )
    assert locked.exit_code == 0
    assert locked.session is not None
    compiled = adapter.run(
        "compile-v013",
        session=locked.session,
        output_argument="output",
    )
    assert compiled.exit_code == 0, compiled.stdout + compiled.stderr
    assert compiled.session is not None
    return compiled.session


def test_frozen_package_matches_complete_lock() -> None:
    package = default_frozen_package()
    package.verify()
    assert len(package.files) == 237
    assert package.source_zip_sha256 == (
        "26ebf87de07c508798fa77511739b08094855186bc9e696a00e2a51c902ca71c"
    )


def test_zero_cost_chain_preserves_prompt_references_and_edit_target(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "product.png"
    _source_image(image_path)
    adapter = HarnessAdapter(default_frozen_package())
    first = _compile(adapter, image_path)
    second = _compile(adapter, image_path)
    assert first["plan"] == second["plan"]

    authorized = adapter.run(
        "authorize",
        session=first,
        text_arguments={"approval-text": "我确认六图规划"},
    )
    assert authorized.exit_code == 0
    assert authorized.session is not None
    generated = adapter.run(
        "generate-next",
        session=authorized.session,
        output_argument="out",
    )
    assert generated.exit_code == 0
    assert generated.result is not None
    request = generated.result["generation_request"]
    assert request["page_index"] == 0
    assert request["output_surface_contract"] == {
        "aspect_ratio": "1:1",
        "minimum_width": 1024,
        "minimum_height": 1024,
        "surface": "TAOBAO_SEARCH_AND_CAROUSEL_SQUARE",
    }
    assert [item["role"] for item in request["reference_allowlist"]] == [
        "PRODUCT_IDENTITY_AUTHORITY"
    ]
    assert request["edit_target"]["evidence_id"] == "evidence-01"
    assert request["edit_target"]["role"] == "PRODUCT_IDENTITY_AUTHORITY"
    prompt_bytes = request["prompt"].encode("utf-8")
    assert hashlib.sha256(prompt_bytes).hexdigest()
    assert generated.artifacts["out"]["prompt"] == request["prompt"]


def test_nonzero_harness_exit_never_returns_a_new_session(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _source_image(image_path)
    adapter = HarnessAdapter(default_frozen_package())
    started = adapter.run(
        "start", session=None, json_arguments={"input": _raw(image_path)}
    )
    assert started.session is not None
    blocked = adapter.run(
        "authorize",
        session=json.loads(json.dumps(started.session, ensure_ascii=False)),
        text_arguments={"approval-text": "确认"},
    )
    assert blocked.exit_code != 0
    assert blocked.session is None
    assert blocked.result is not None
    assert blocked.result["status"] == "BLOCKED"
    assert "AWAITING_AUTHORIZATION" in blocked.result["error"]


def test_persisted_session_can_resume_after_adapter_restart(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _source_image(image_path)
    package = default_frozen_package()
    first_adapter = HarnessAdapter(package)
    started = first_adapter.run(
        "start", session=None, json_arguments={"input": _raw(image_path)}
    )
    persisted = json.loads(json.dumps(started.session, ensure_ascii=False))
    restarted_adapter = HarnessAdapter(package)
    locked = restarted_adapter.run(
        "lock-identity",
        session=persisted,
        json_arguments={"identity": _identity(image_path)},
    )
    assert locked.exit_code == 0
    assert locked.session is not None
    assert locked.session["state"] == "IDENTITY_LOCKED"
