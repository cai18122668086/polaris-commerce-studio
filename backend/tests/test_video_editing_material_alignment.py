from types import SimpleNamespace

import pytest

from app.video_editing_contracts import (
    SemanticPlan,
    Transcript,
    TranscriptToken,
    TranscriptUtterance,
)
from app.video_editing_material_alignment import alignment_input, placement_receipt
from app.video_editing_overlay_templates import overlay_template
from app.video_editing_template_styles import (
    style_candidate_ids,
    style_policy,
    validate_template_style,
)


def transcript():
    words = ["先", "复制", "商品链接", "再", "上传", "产品图", "最后", "生成", "详情图"]
    return Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=9000,
        provider="fixture",
        model="measured",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"w{i}", text=w, start_ms=i * 1000, end_ms=(i + 1) * 1000
            )
            for i, w in enumerate(words)
        ],
        utterances=[
            TranscriptUtterance(
                id=f"u{i}",
                text="".join(words[i * 3 : i * 3 + 3]),
                token_ids=[f"w{n}" for n in range(i * 3, i * 3 + 3)],
                start_ms=i * 3000,
                end_ms=(i + 1) * 3000,
            )
            for i in range(3)
        ],
    )


def cards():
    return [
        {
            "id": "upload-detail",
            "kind": "image",
            "sha256": "c" * 64,
            "viewed_identity": "详情图",
            "semantic_use": "生成的商品详情图效果",
        },
        {
            "id": "upload-link",
            "kind": "video",
            "sha256": "d" * 64,
            "viewed_identity": "复制商品链接",
            "semantic_use": "商品链接复制操作录屏",
        },
        {
            "id": "upload-irrelevant",
            "kind": "image",
            "sha256": "e" * 64,
            "viewed_identity": "旅游风景",
            "semantic_use": "海边日落",
        },
    ]


def test_descriptions_retrieve_sentence_order_independently_of_upload_order():
    result = alignment_input(transcript(), cards())
    assert result["materials"][0]["candidates"][0]["id"] == "u2"
    assert result["materials"][1]["candidates"][0]["id"] == "u0"
    assert result["materials"][2]["status"] == "unmatched"
    assert result["materials"][2]["candidates"] == []
    assert result == alignment_input(transcript(), cards())
    changed = cards()
    changed[0]["semantic_use"] = "改用产品图"
    assert (
        result["input_sha256"] != alignment_input(transcript(), changed)["input_sha256"]
    )


def test_final_receipt_binds_real_words_and_preserves_unused_materials():
    plan = SemanticPlan(
        audience_question="如何生成详情图",
        argument_outline=["上传与生成"],
        style_reason="同套图卡",
        beats=[
            {
                "id": "detail",
                "first_token_id": "w6",
                "last_token_id": "w8",
                "relation": "explanation",
                "group_id": "CX-G01",
                "reason": "展示这一句提到的详情图",
                "asset_ids": ["upload-detail"],
            }
        ],
    )
    result = placement_receipt(plan, transcript(), cards())
    assert result["placements"][0]["start_ms"] == 6000
    assert result["placements"][0]["spoken_text"] == "最后生成详情图"
    assert result["unused_material_ids"] == ["upload-irrelevant", "upload-link"]
    assert result["render_replanning"] is False
    plan.beats[0].asset_ids = ["invented"]
    with pytest.raises(ValueError, match="unknown material"):
        placement_receipt(plan, transcript(), cards())


def test_named_action_is_preserved_when_the_picture_noun_is_a_synonym():
    material = {
        "id": "upload-photo",
        "kind": "video",
        "sha256": "f" * 64,
        "viewed_identity": "上传实拍图",
        "semantic_use": "上传实拍图",
    }
    result = alignment_input(transcript(), [material])
    assert result["materials"][0]["candidates"][0]["id"] == "u1"
    assert "上传" in result["materials"][0]["candidates"][0]["matched_terms"]


@pytest.mark.parametrize(
    "template_id", ["rotation-cards-v1", "presenter-openings-v1", "chenxi-broll-v1"]
)
def test_new_suite_rejects_shared_effects_outside_its_family(template_id):
    template = overlay_template(template_id)
    policy = style_policy(template, cohesive=True)
    candidates = style_candidate_ids(template, {"template_style": policy}, None)
    assert "AH-S05" not in candidates
    signature = policy["signature_group_ids"][0]
    plan = SimpleNamespace(beats=[SimpleNamespace(group_id=signature)])
    validate_template_style(plan, {"template_style": policy})
    plan.beats.append(SimpleNamespace(group_id="AH-S05"))
    with pytest.raises(ValueError, match="成套模板以外"):
        validate_template_style(plan, {"template_style": policy})
