"""Distinct styles must survive selection through charging and native adoption."""

from types import SimpleNamespace

import pytest
from app.errors import ApiError
from app.motion_library import atomic_json
from app.video_editing_contracts import SemanticPlan, Transcript, TranscriptToken
from app.video_editing_overlay_templates import overlay_template
from app.video_editing_planner import validate_plan
from app.video_editing_planning_store import require_template_group_capacity
from app.video_editing_template_styles import (
    adapt_style_text_relations,
    style_candidate_ids,
    style_policy,
    validate_template_style,
)
from app.video_editing_word_bindings import negation_token_positions


def test_rotation_cannot_charge_for_shared_subtitles_without_its_three_images():
    template = overlay_template("rotation-cards-v1")
    snapshot = {
        "overlay_template": template,
        "choice_snapshot": {"notes": []},
        "planning_runtime": {
            "template_style": style_policy(template),
            "unavailable_template_groups": {
                "CX-G04": ["missing-three-distinct-project-images"]
            },
        },
    }
    # Eleven other usable groups would meet the old numeric capacity check.
    with pytest.raises(ApiError) as error:
        require_template_group_capacity(snapshot)
    assert error.value.code == "EDITING_TEMPLATE_STYLE_UNAVAILABLE"
    snapshot["planning_runtime"]["unavailable_template_groups"] = {}
    require_template_group_capacity(snapshot)
    snapshot["choice_snapshot"]["notes"] = [
        {"target_kind": "group", "target_id": "CX-G04", "choice": "avoid"}
    ]
    with pytest.raises(ApiError):
        require_template_group_capacity(snapshot)


def test_signature_is_required_only_for_new_preparations():
    policy = style_policy(overlay_template("rotation-cards-v1"))
    generic = SimpleNamespace(
        beats=[
            SimpleNamespace(group_id=g)
            for g in ["SG-S03", "AH-S05", "SG-S02", "SG-S06", "BG-S04"]
        ]
    )
    validate_template_style(generic, {})  # Historical captured request has no opt-in.
    with pytest.raises(ValueError, match="招牌动效"):
        validate_template_style(generic, {"template_style": policy})
    generic.beats.append(SimpleNamespace(group_id="CX-G04"))
    validate_template_style(generic, {"template_style": policy})
    assert style_policy(overlay_template("product-explainer-v1")) is None
    assert style_policy(overlay_template("knowledge-talk-v1")) is None


@pytest.mark.parametrize("selected", [0, 1, 2])
def test_rotation_image_shortage_blocks_billing_even_with_shared_groups(selected):
    template = overlay_template("rotation-cards-v1")
    snapshot = {
        "overlay_template": template,
        "choice_snapshot": {"notes": []},
        "planning_runtime": {
            "template_style": style_policy(template),
            "unavailable_template_groups": {},
            "project_image_requirements": [
                {
                    "group_id": "CX-G04",
                    "selected_distinct_images": selected,
                    "required_distinct_images": 3,
                }
            ],
        },
    }
    with pytest.raises(ApiError) as error:
        require_template_group_capacity(snapshot)
    assert error.value.code == "EDITING_TEMPLATE_STYLE_UNAVAILABLE"
    assert "3 张不同图片" in error.value.message
    snapshot["planning_runtime"]["project_image_requirements"][0][
        "selected_distinct_images"
    ] = 3
    require_template_group_capacity(snapshot)


@pytest.mark.parametrize(
    "words, expected",
    [
        (["分", "别", "解决"], set()),
        (["分别", "解决"], set()),
        (["别", "跳过条件"], {0}),
        (["分", "，", "别", "删掉否定"], {2}),
        (["不是", "四种商品"], {0}),
        (["not", "a", "product"], {0}),
        (["never", "omit", "conditions"], {0}),
        (["knot", "size"], set()),
    ],
)
def test_separately_is_not_a_negation_but_real_imperatives_remain_protected(
    words, expected
):
    tokens = [
        TranscriptToken(id=str(i), text=word, start_ms=i * 100, end_ms=(i + 1) * 100)
        for i, word in enumerate(words)
    ]
    assert negation_token_positions(tokens) == expected


def test_relation_projection_preserves_every_render_field_and_keeps_strict_validation(
    tmp_path,
):
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=6000,
        provider="fixture",
        model="fixture",
        language="zh",
        utterances=[],
        tokens=[
            TranscriptToken(id=str(i), text=w, start_ms=i * 1000, end_ms=i * 1000 + 500)
            for i, w in enumerate("一键复刻风格")
        ],
    )
    plan = SemanticPlan.model_validate(
        {
            "audience_question": "如何参考",
            "argument_outline": ["参考方向"],
            "style_reason": "协议夹具",
            "beats": [
                {
                    "id": "text",
                    "first_token_id": "0",
                    "last_token_id": "5",
                    "group_id": "JJ-S01",
                    "relation": "explanation",
                    "reason": "完整短句在一个原生槽显示",
                    "native_text": [
                        {
                            "path": "/content/main",
                            "first_token_id": "0",
                            "last_token_id": "1",
                        },
                        {
                            "path": "/content/detail",
                            "first_token_id": "2",
                            "last_token_id": "5",
                        },
                    ],
                    "relation_items": [
                        {
                            "id": "a",
                            "first_token_id": "2",
                            "last_token_id": "3",
                            "native_text_paths": ["/content/detail"],
                        },
                        {
                            "id": "b",
                            "first_token_id": "4",
                            "last_token_id": "5",
                            "native_text_paths": ["/content/detail"],
                        },
                    ],
                }
            ],
        }
    )
    atomic_json(
        tmp_path / "catalog/groups.json",
        {
            "groups": [
                {
                    "id": "JJ-S01",
                    "input_template": "effect.json",
                    "input_schema": "schema.json",
                    "backend": "subtitle",
                }
            ]
        },
    )
    atomic_json(tmp_path / "catalog/external-resources.json", {"resources": []})
    atomic_json(
        tmp_path / "effect.json", {"content": {"main": "一键", "detail": "复刻风格"}}
    )
    atomic_json(tmp_path / "schema.json", {"type": "object"})
    with pytest.raises(ValueError):
        validate_plan(plan, transcript, tmp_path, set())
    before = plan.model_dump(mode="json")
    adjusted, receipt = adapt_style_text_relations(
        plan, transcript, {"template_style": {}}
    )
    # Presence of a real opted-in policy is required; an empty value is legacy.
    assert adjusted is plan and receipt is None
    adjusted, receipt = adapt_style_text_relations(
        plan, transcript, {"template_style": {"version": "tengli.template-style/1"}}
    )
    assert receipt["visual_fields_changed"] is False
    assert adjusted.beats[0].model_dump(exclude={"relation_items"}) == plan.beats[
        0
    ].model_dump(exclude={"relation_items"})
    assert plan.model_dump(mode="json") == before
    validate_plan(adjusted, transcript, tmp_path, set())
    plan.beats[0].relation = "parallel"
    parallel, receipt = adapt_style_text_relations(
        plan, transcript, {"template_style": {"version": "tengli.template-style/1"}}
    )
    assert parallel is plan and receipt is None
    with pytest.raises(ValueError):
        validate_plan(parallel, transcript, tmp_path, set())


def test_scoped_style_pool_excludes_unavailable_and_avoided_members():
    template = overlay_template("rotation-cards-v1")
    runtime = {
        "template_style": style_policy(template),
        "unavailable_template_groups": {"BG-S06": ["not_spoken"]},
    }
    choices = {
        "notes": [{"target_kind": "group", "target_id": "AHG-S02", "choice": "avoid"}]
    }
    pool = style_candidate_ids(template, runtime, choices)
    assert pool == (
        {s["group_id"] for s in template["slots"]} - {"BG-S06", "AHG-S02"}
    ) | {"Z-M00"}
    assert style_candidate_ids(template, {}, choices) is None
