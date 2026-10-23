from copy import deepcopy

import pytest

from app.replica_layout import (
    bind_module_text,
    exact_review_context,
    validate_reference_layouts,
)


def source_layout():
    regions = [
        ("T1", "headline", "dominant", "line1", "每一次排毛", [40, 110, 950, 230]),
        ("T2", "connector", "small", "line2", "都是一次", [30, 240, 200, 350]),
        ("T3", "headline", "dominant", "line2", "营养补给", [220, 240, 950, 350]),
        ("T4", "badge", "small", "pill", "专注宠物健康", [650, 10, 950, 60]),
    ]
    return {
        "units": [
            {
                "reference_unit_id": "R001",
                "reference_sha256": "a" * 64,
                "reference_product_present": True,
                "has_poster_text": True,
                "layout_anchors": [
                    {"label": "small package", "bbox": [480, 540, 950, 910]}
                ],
                "typography_notes": (
                    "Two dominant lines with a small connector on line two."
                ),
                "text_regions": [
                    dict(
                        zip(
                            (
                                "id",
                                "role",
                                "font_tier",
                                "line_group",
                                "observed_text",
                                "bbox",
                            ),
                            row,
                            strict=True,
                        )
                    )
                    for row in regions
                ],
            }
        ]
    }


def bindings():
    return {
        "M001": {
            "module_id": "M001",
            "reference_sha256": "a" * 64,
            "product_visibility": "visible_product",
            "text_bindings": [
                {
                    "region_id": "T1",
                    "action": "render",
                    "copy_unit_index": 0,
                    "fragment": "三拼冻干",
                },
                {
                    "region_id": "T2",
                    "action": "render",
                    "copy_unit_index": 0,
                    "fragment": "一口",
                },
                {
                    "region_id": "T3",
                    "action": "render",
                    "copy_unit_index": 0,
                    "fragment": "多重营养",
                },
                {
                    "region_id": "T4",
                    "action": "render",
                    "copy_unit_index": 1,
                    "fragment": "全阶段适用",
                },
            ],
        }
    }


MODULE = {
    "id": "M001",
    "reference_unit_id": "R001",
    "copy_units": ["三拼冻干 一口多重营养", "全阶段适用"],
}


def test_two_dominant_lines_keep_small_connector_and_replace_source_capsule():
    layouts = validate_reference_layouts(source_layout(), {"R001": "a" * 64})
    scope = bindings()
    scope["M001"]["text_bindings"][1].update(
        font_tier="dominant", bbox=[0, 0, 1000, 900]
    )
    result = bind_module_text(scope, [MODULE], layouts)["M001"]
    text = result["text_bindings"]
    assert [row["font_tier"] for row in text] == [
        "dominant",
        "small",
        "dominant",
        "small",
    ]
    assert text[1]["line_group"] == text[2]["line_group"] == "line2"
    assert text[1]["bbox"] == [30, 240, 200, 350]
    assert text[3]["render_text"] == "全阶段适用"
    assert all("observed_text" not in row for row in text)


@pytest.mark.parametrize(
    "bad",
    [
        "unapproved_pill",
        "missing_slot",
        "duplicate_slot",
        "omit_headline",
        "wrong_copy_index",
    ],
)
def test_untrusted_copy_mapping_cannot_authorize_source_slogan_or_drop_headline(bad):
    scope = bindings()
    rows = scope["M001"]["text_bindings"]
    if bad == "unapproved_pill":
        rows[-1]["fragment"] = "专注宠物健康"
    elif bad == "missing_slot":
        rows.pop()
    elif bad == "duplicate_slot":
        rows[-1]["region_id"] = "T1"
    elif bad == "omit_headline":
        rows[0].update(
            action="omit_unsupported_copy",
            reason="The source claim has no supporting product facts.",
            retain_carrier=True,
        )
    else:
        rows[-1]["copy_unit_index"] = True
    with pytest.raises(ValueError):
        bind_module_text(scope, [MODULE], {"R001": source_layout()["units"][0]})


@pytest.mark.parametrize(
    "bad", ["source_hash", "duplicate_region", "out_of_bounds", "absent_text"]
)
def test_source_layout_must_bind_real_crop_and_valid_regions(bad):
    value = source_layout()
    row = value["units"][0]
    if bad == "source_hash":
        row["reference_sha256"] = "b" * 64
    elif bad == "duplicate_region":
        row["text_regions"].append(deepcopy(row["text_regions"][0]))
    elif bad == "out_of_bounds":
        row["text_regions"][0]["bbox"][2] = 1001
    else:
        row["has_poster_text"] = False
    with pytest.raises(ValueError):
        validate_reference_layouts(value, {"R001": "a" * 64})


def test_fresh_review_excludes_wrong_plan_description_and_other_module_constraints():
    module = {
        **MODULE,
        "visual_contract": {"typography_structure": "three huge rows"},
        "generation_brief": "make every line huge",
    }
    scope = {
        "module_id": "M001",
        "required_identity_checks": ["Visible real package"],
        "layout_anchors": [{"label": "three huge rows"}],
        "composition_notes": "three huge rows",
    }
    context = {
        "user_facts": "Verified product facts",
        "reference_layouts": source_layout(),
        "module_constraints": {
            "M001": scope,
            "M003": {"instruction": "show loose food"},
        },
    }
    result = exact_review_context(module, context)
    assert result["user_context"] == {"user_facts": "Verified product facts"}
    assert "visual_contract" not in result["module"]
    assert "generation_brief" not in result["module"]
    assert result["module_constraints"] == {
        "module_id": "M001",
        "required_identity_checks": ["Visible real package"],
    }
