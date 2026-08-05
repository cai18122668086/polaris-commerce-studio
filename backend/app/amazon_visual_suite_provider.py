"""Independent manifest-gated adapter for the Amazon 21-image suite."""

# The authoritative 21-row task table intentionally keeps buyer-facing copy
# visible beside each stable item key; wrapping those values would obscure review.
# ruff: noqa: E501

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import gcd
from typing import Any

from app.amazon_visual_suite_contract import (
    AMAZON_DEFAULT_MARKETPLACE,
    AMAZON_MARKETPLACES,
)
from app.new_detail_skill_provider import (
    SKILL_ADAPTER_CONFIGURATION_KEY,
    AdapterValidationError,
    BundledSkillManifestValidator,
    ManifestValidator,
    job_configuration_from,
    rejected_result,
)
from app.new_image_skill_provider import (
    SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION,
    NewImageSkillContractError,
    compact_prompt_input,
    optional_string,
    optional_string_list,
    require_asset_ids,
    role_labelled_assets,
    validate_optional_asset_ids,
)
from app.provider import Provider, ProviderOutcome, ProviderRequest, ProviderResult
from app.skill_runtime import SkillRuntimeError

AMAZON_VISUAL_SUITE_OPERATION = "amazon_visual_suite"
AMAZON_VISUAL_SUITE_SKILL_ID = "xinghe-amazon-visual-suite"
AMAZON_ADAPTER_CONTRACT_VERSION = SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION
AMAZON_EXPECTED_ITEM_COUNT = 21
AMAZON_AUDIT_CONFIGURATION_KEY = "amazon_visual_suite_audit"
AMAZON_PLAN_CONFIGURATION_KEY = "amazon_visual_suite_plan"
AMAZON_PLANNING_POLICY_VERSION = "amazon-visual-suite-planning-v2"


@dataclass(frozen=True)
class AmazonItemSpec:
    item_key: str
    group: str
    group_ordinal: int
    width: int
    height: int
    asset_type: str
    buyer_question: str
    selling_point: str
    visual_proof: str
    headline: str
    subcopy: str
    layout_direction: str
    source_material: str
    risk_note: str


_CONFIDENCE_RULE = (
    "Use confirmed facts first; soften reasonable inferences; omit every "
    "needs-confirmation claim from the image."
)
_GLOBAL_RISK_GUARD = (
    "Preserve product identity and physical logic. Do not invent parts, SKUs, "
    "accessories, packaging facts, certifications, ratings, rankings, test "
    "results, endorsements, or absolute performance claims."
)


def _item_spec(
    item_key: str,
    group: str,
    group_ordinal: int,
    width: int,
    height: int,
    *,
    asset_type: str,
    buyer_question: str,
    selling_point: str,
    visual_proof: str,
    headline: str,
    subcopy: str,
    layout_direction: str,
    source_material: str,
    risk_note: str,
) -> AmazonItemSpec:
    return AmazonItemSpec(
        item_key=item_key,
        group=group,
        group_ordinal=group_ordinal,
        width=width,
        height=height,
        asset_type=asset_type,
        buyer_question=buyer_question,
        selling_point=selling_point,
        visual_proof=visual_proof,
        headline=headline,
        subcopy=subcopy,
        layout_direction=layout_direction,
        source_material=source_material,
        risk_note=risk_note,
    )


def _build_item_specs() -> tuple[AmazonItemSpec, ...]:
    return (
        _item_spec(
            "MAIN-01",
            "main",
            1,
            2000,
            2000,
            asset_type="Search/result main image",
            buyer_question="Can I recognize the exact product quickly?",
            selling_point="Show the exact provided product clearly and truthfully.",
            visual_proof=(
                "Real product on a pure white background with clear edges, "
                "centered composition, and high subject occupancy."
            ),
            headline="No headline or other on-image copy.",
            subcopy="No subcopy, labels, badges, or icons.",
            layout_direction=(
                "Square white canvas; center the complete product and keep all "
                "product edges visible."
            ),
            source_material="Use the real white_background_product source image.",
            risk_note=(
                "No lifestyle scene, props, text, ratings, claims, fake packaging, "
                "or accessories not present in the provided source."
            ),
        ),
        _item_spec(
            "SECONDARY-01",
            "secondary",
            1,
            1200,
            1600,
            asset_type="Core benefit secondary image",
            buyer_question="What is the main reason to buy?",
            selling_point="Lead with the strongest confirmed product benefit.",
            visual_proof=(
                "Show the benefit in one scene or a clean studio composition so "
                "the proof is understood before the copy is read."
            ),
            headline="One short shopper-facing core-benefit headline.",
            subcopy="Optional short support copy using confirmed facts only.",
            layout_direction="One dominant benefit, one focal product, uncluttered 3:4 layout.",
            source_material="Use product and scene references that directly support the benefit.",
            risk_note="Do not use an unsupported superlative or absolute performance claim.",
        ),
        _item_spec(
            "SECONDARY-02",
            "secondary",
            2,
            1200,
            1600,
            asset_type="Pain-point scene secondary image",
            buyer_question="What problem does it solve?",
            selling_point="Connect one confirmed use case to one buyer pain point.",
            visual_proof="Use a real context contrast, user frustration, or conservative before/after.",
            headline="One short problem-to-result headline without guarantees.",
            subcopy="Optional brief context; avoid unproven outcome language.",
            layout_direction="Single scenario or simple two-state contrast; keep the product unmistakable.",
            source_material="Use product and scene references; treat unseen outcomes as unknown.",
            risk_note="Do not fabricate dramatic before/after results or user testimony.",
        ),
        _item_spec(
            "SECONDARY-03",
            "secondary",
            3,
            1200,
            1600,
            asset_type="Function/structure secondary image",
            buyer_question="How does it work?",
            selling_point="Explain one confirmed mechanism, structure, material, or feature.",
            visual_proof="Use structural callouts, a mechanism view, or a truthful feature close-up.",
            headline="One short function or feature headline grounded in visible evidence.",
            subcopy="Use only concise labels that remain readable at listing size.",
            layout_direction="Macro or structure-led layout with a clear visual hierarchy.",
            source_material="Prioritize product_detail and white_background_product references.",
            risk_note="Do not invent internal construction, materials, technology, or test data.",
        ),
        _item_spec(
            "SECONDARY-04",
            "secondary",
            4,
            1200,
            1600,
            asset_type="Size/fit/compatibility secondary image",
            buyer_question="Will it fit my use case?",
            selling_point="Clarify confirmed size, scale, version, or compatibility information.",
            visual_proof="Use scale reference, dimensions, model choices, or an explicit caveat.",
            headline="One short size, fit, or compatibility headline.",
            subcopy="State measurements or compatibility only when supplied or visibly confirmed.",
            layout_direction="Scale-led layout with sparse, legible measurements or choices.",
            source_material="Use product, package, and supplied listing facts for exact specifications.",
            risk_note="Never infer dimensions, capacity, model compatibility, or fit guarantees.",
        ),
        _item_spec(
            "SECONDARY-05",
            "secondary",
            5,
            1200,
            1600,
            asset_type="Use-steps secondary image",
            buyer_question="Is it easy to use?",
            selling_point="Show the confirmed operating, installation, opening, cleaning, or daily flow.",
            visual_proof="Use a clear three-step action sequence or truthful hand interaction.",
            headline="One short ease-of-use headline without an unsupported time claim.",
            subcopy="Up to three short action labels in the correct order.",
            layout_direction="Readable three-step flow with consistent product identity in every step.",
            source_material="Use product and detail references; use scene references only when relevant.",
            risk_note="Do not invent steps, hand grips, opening direction, or installation behavior.",
        ),
        _item_spec(
            "SECONDARY-06",
            "secondary",
            6,
            1200,
            1600,
            asset_type="Trust/package recap secondary image",
            buyer_question="What exactly do I get and why should I trust it?",
            selling_point="Recap confirmed included items, packaging, care, or strongest truthful reasons.",
            visual_proof="Show provided package contents or a conservative selling-point summary.",
            headline="One short package or trust recap headline.",
            subcopy="List only supplied or visibly present items and confirmed care facts.",
            layout_direction="Package or recap layout with a complete, countable set of visible items.",
            source_material="Prioritize package_reference, product_detail, and the supplied listing facts.",
            risk_note="Do not add accessories, certifications, warranties, reviews, or package contents.",
        ),
        _item_spec(
            "A-DESKTOP-01",
            "a_desktop",
            1,
            1464,
            600,
            asset_type="Desktop A+ brand/product opening",
            buyer_question="What is this product's promise?",
            selling_point="Open with the strongest confirmed product promise.",
            visual_proof="Wide hero scene with the product and campaign headline.",
            headline="One concise campaign headline derived from confirmed product facts.",
            subcopy="One short supporting line at most.",
            layout_direction="Wide hero; center-safe product and copy; clear opening focal point.",
            source_material="Use product, scene, and brand references while preserving exact identity.",
            risk_note="Do not turn a product promise into a guarantee or unsupported superlative.",
        ),
        _item_spec(
            "A-DESKTOP-02",
            "a_desktop",
            2,
            1464,
            600,
            asset_type="Desktop A+ buyer-demand module",
            buyer_question="Why do I need it?",
            selling_point="Address the highest-priority confirmed pain point or desired result.",
            visual_proof="Show one high-priority pain point or desired result in context.",
            headline="One concise buyer-demand headline.",
            subcopy="One conservative support line without promised outcomes.",
            layout_direction="Wide single-scene story with obvious problem-to-product relationship.",
            source_material="Use product and relevant scene references plus supplied buyer facts.",
            risk_note="No fabricated frustration, testimonial, result, or before/after evidence.",
        ),
        _item_spec(
            "A-DESKTOP-03",
            "a_desktop",
            3,
            1464,
            600,
            asset_type="Desktop A+ core-feature module",
            buyer_question="What makes it different?",
            selling_point="Explain one confirmed mechanism, structure, technology, craft, or detail.",
            visual_proof="Use mechanism, structure, craft, or close-detail evidence.",
            headline="One short differentiation headline grounded in confirmed evidence.",
            subcopy="Use sparse feature labels only where legible.",
            layout_direction="Wide structure or macro composition with evidence larger than text.",
            source_material="Prioritize product_detail and white_background_product references.",
            risk_note="Do not invent materials, construction, technology, patents, or lab evidence.",
        ),
        _item_spec(
            "A-DESKTOP-04",
            "a_desktop",
            4,
            1464,
            600,
            asset_type="Desktop A+ scenario-proof module",
            buyer_question="Where does it fit in real life?",
            selling_point="Show a plausible confirmed use environment and product scale.",
            visual_proof="Lifestyle or use environment with credible product scale and physics.",
            headline="One short use-scenario headline.",
            subcopy="Optional context line; do not imply universal suitability.",
            layout_direction="Wide lifestyle scene with obvious product presence and credible scale.",
            source_material="Use product and relevant scene references.",
            risk_note="Do not distort scale, contact, shadow, perspective, hand grip, or wearing fit.",
        ),
        _item_spec(
            "A-DESKTOP-05",
            "a_desktop",
            5,
            1464,
            600,
            asset_type="Desktop A+ detail-trust module",
            buyer_question="Can I trust the material and build?",
            selling_point="Build trust with visible construction, finish, texture, parts, or detail.",
            visual_proof="Use a macro, texture, parts, finish, or visible-construction view.",
            headline="One short detail-trust headline using non-technical truthful language.",
            subcopy="Name materials or finishes only when provided or visibly confirmed.",
            layout_direction="Wide macro-led composition; keep detail evidence crisp and central.",
            source_material="Prioritize product_detail and package_reference images.",
            risk_note="Do not infer material grade, durability, certification, or performance tests.",
        ),
        _item_spec(
            "A-DESKTOP-06",
            "a_desktop",
            6,
            1464,
            600,
            asset_type="Desktop A+ comparison/choice module",
            buyer_question="Why choose this version?",
            selling_point="Help the buyer choose using confirmed versions, sizes, or features.",
            visual_proof="Use a conservative comparison, size/version guide, or feature matrix.",
            headline="One short choice-guidance headline.",
            subcopy="Use only the few confirmed distinctions needed for a decision.",
            layout_direction="Wide, sparse comparison with readable columns and clear SKU identity.",
            source_material="Use supplied listing, product, and package facts for every comparison point.",
            risk_note="No fake competitor, superiority, compatibility, ranking, or unprovided SKU claim.",
        ),
        _item_spec(
            "A-DESKTOP-07",
            "a_desktop",
            7,
            1464,
            600,
            asset_type="Desktop A+ closing-summary module",
            buyer_question="What should I remember before purchase?",
            selling_point="Close with the product and three or four strongest confirmed reasons.",
            visual_proof="Cohesive product recap with distinct, truthful visual proof cues.",
            headline="One short closing headline.",
            subcopy="Three or four concise confirmed reasons at most.",
            layout_direction="Wide closing hero or recap; cohesive, spacious, and purchase-oriented.",
            source_material="Use the strongest product, detail, scene, package, and brand references.",
            risk_note="Do not crowd the module or introduce any new unproven claim at closing.",
        ),
        _item_spec(
            "A-MOBILE-01",
            "a_mobile",
            1,
            1600,
            1200,
            asset_type="Mobile A+ product opening",
            buyer_question="What is this product's promise?",
            selling_point="Open with the same strongest confirmed promise as desktop A+.",
            visual_proof="Large product, short headline, and one dominant focal point.",
            headline="A shorter mobile version of the confirmed campaign headline.",
            subcopy="One very short supporting line at most.",
            layout_direction="Mobile-first 4:3; larger product, single focal point, phone-readable copy.",
            source_material="Use product, scene, and brand references; compose independently for mobile.",
            risk_note="Do not stretch or merely crop the desktop module; avoid edge-dependent content.",
        ),
        _item_spec(
            "A-MOBILE-02",
            "a_mobile",
            2,
            1600,
            1200,
            asset_type="Mobile A+ buyer-demand module",
            buyer_question="Why do I need it?",
            selling_point="Address the same highest-priority buyer demand as desktop A+.",
            visual_proof="One scene or action with minimal labels.",
            headline="One short phone-readable buyer-demand headline.",
            subcopy="One minimal support line without promised outcomes.",
            layout_direction="Mobile-first one-scene composition with immediate problem-to-product clarity.",
            source_material="Use product and relevant scene references; compose independently for mobile.",
            risk_note="No fabricated result or dense labels; do not reuse a stretched desktop layout.",
        ),
        _item_spec(
            "A-MOBILE-03",
            "a_mobile",
            3,
            1600,
            1200,
            asset_type="Mobile A+ core-feature module",
            buyer_question="What makes it different?",
            selling_point="Explain the same confirmed core feature as desktop A+.",
            visual_proof="A macro or structure detail that remains readable at phone width.",
            headline="One short evidence-led feature headline.",
            subcopy="Up to three short labels only if phone-readable.",
            layout_direction="Mobile-first macro or structure view; evidence dominates copy.",
            source_material="Prioritize product_detail and product references; compose independently.",
            risk_note="Do not invent hidden construction or shrink desktop callouts into unreadable text.",
        ),
        _item_spec(
            "A-MOBILE-04",
            "a_mobile",
            4,
            1600,
            1200,
            asset_type="Mobile A+ scenario-proof module",
            buyer_question="Where does it fit in real life?",
            selling_point="Show the same plausible use environment as desktop A+.",
            visual_proof="Make product scale and context obvious within one second.",
            headline="One short use-scenario headline.",
            subcopy="Optional single context line.",
            layout_direction="Mobile-first lifestyle scene with large product and unmistakable scale.",
            source_material="Use product and scene references; compose independently for mobile.",
            risk_note="Do not distort physical scale or hide the product in a busy mobile scene.",
        ),
        _item_spec(
            "A-MOBILE-05",
            "a_mobile",
            5,
            1600,
            1200,
            asset_type="Mobile A+ detail-trust module",
            buyer_question="Can I trust the material and build?",
            selling_point="Show the same confirmed detail-trust evidence as desktop A+.",
            visual_proof="Prefer a detail crop or material proof over dense text.",
            headline="One short detail-trust headline.",
            subcopy="One short confirmed material or finish note at most.",
            layout_direction="Mobile-first detail crop with crisp texture and minimal copy.",
            source_material="Prioritize product_detail and package references; compose independently.",
            risk_note="Do not infer material grade, durability, certification, or test results.",
        ),
        _item_spec(
            "A-MOBILE-06",
            "a_mobile",
            6,
            1600,
            1200,
            asset_type="Mobile A+ comparison/choice module",
            buyer_question="Why choose this version?",
            selling_point="Simplify the same confirmed choice guidance as desktop A+.",
            visual_proof="Show only the fewest useful confirmed comparison points.",
            headline="One short choice-guidance headline.",
            subcopy="Use the minimum phone-readable confirmed distinctions.",
            layout_direction="Mobile-first sparse comparison with large labels and clear SKU identity.",
            source_material="Use supplied listing, product, and package facts; compose independently.",
            risk_note="No competitor claims, tiny feature matrix, unprovided SKU, or compatibility claim.",
        ),
        _item_spec(
            "A-MOBILE-07",
            "a_mobile",
            7,
            1600,
            1200,
            asset_type="Mobile A+ closing-summary module",
            buyer_question="What should I remember before purchase?",
            selling_point="Close with the product and strongest confirmed reasons from desktop A+.",
            visual_proof="Clear product recap without a crowded checklist.",
            headline="One short closing headline.",
            subcopy="Up to three concise confirmed reasons.",
            layout_direction="Mobile-first closing hero; clear hierarchy, large product, spacious recap.",
            source_material="Use the strongest supplied references; compose independently for mobile.",
            risk_note="Do not crowd the checklist, introduce a new claim, or stretch the desktop close.",
        ),
    )


AMAZON_ITEM_SPECS = _build_item_specs()
AMAZON_ITEM_KEYS = tuple(spec.item_key for spec in AMAZON_ITEM_SPECS)
_AMAZON_ITEM_SPEC_BY_KEY = {spec.item_key: spec for spec in AMAZON_ITEM_SPECS}


def amazon_item_spec(item_key: str) -> AmazonItemSpec:
    try:
        return _AMAZON_ITEM_SPEC_BY_KEY[item_key]
    except KeyError as exc:
        raise AdapterValidationError(
            "AMAZON_ITEM_KEY_INVALID",
            f"Unknown Amazon deliverable item key: {item_key}.",
        ) from exc


def validate_amazon_item_keys(item_keys: Sequence[str]) -> tuple[str, ...]:
    """Validate the exact stable 21-key inventory and ordering."""

    normalized = tuple(item_keys)
    if normalized != AMAZON_ITEM_KEYS:
        missing = [key for key in AMAZON_ITEM_KEYS if key not in normalized]
        extra = [key for key in normalized if key not in AMAZON_ITEM_KEYS]
        raise AdapterValidationError(
            "AMAZON_ITEM_INVENTORY_INVALID",
            (
                "Amazon visual suite requires the canonical 21-item inventory; "
                f"missing={missing}, extra={extra}."
            ),
        )
    return normalized


def validate_amazon_planner_payload(payload: object) -> dict[str, Any]:
    """Validate one auditable Product Master and the canonical 21-row plan."""

    from app.xinghe_agent import (
        _AMAZON_SCREEN_BACKGROUND_SYSTEMS,
        XingheAgentError,
        validate_planner_payload,
    )

    if isinstance(payload, Mapping):
        raw_plan = payload.get("plan")
        if isinstance(raw_plan, Mapping):
            raw_diversity_lock = raw_plan.get("layout_diversity_lock")
            if isinstance(raw_diversity_lock, Mapping):
                raw_maximum = raw_diversity_lock.get("max_same_layout_family")
                if (
                    isinstance(raw_maximum, int)
                    and not isinstance(raw_maximum, bool)
                    and raw_maximum != 2
                ):
                    raise XingheAgentError(
                        "AMAZON_LAYOUT_DIVERSITY_INVALID",
                        (
                            "Amazon planning requires "
                            "max_same_layout_family to be exactly 2."
                        ),
                        json_pointer=(
                            "/plan/layout_diversity_lock/"
                            "max_same_layout_family"
                        ),
                    )

    structured = validate_planner_payload(
        payload,
        AMAZON_EXPECTED_ITEM_COUNT,
        preserve_protocol_fields=True,
        require_cross_page_locks=True,
        enforce_background_repeat_limit=False,
    )
    analysis = structured["analysis"]
    plan = structured["plan"]
    product_master = analysis.get("product_master_description")
    if not isinstance(product_master, Mapping) or not product_master:
        raise XingheAgentError(
            "AMAZON_PRODUCT_MASTER_INVALID",
            "Amazon planning requires a non-empty Product Master Description.",
            json_pointer="/analysis/product_master_description",
        )
    for key in (
        "silhouette_and_proportions",
        "color_and_material_appearance",
        "logos_labels_and_patterns",
        "structural_parts",
        "scale_and_physics",
        "unknowns",
    ):
        value = product_master.get(key)
        valid = (
            isinstance(value, list)
            if key == "unknowns"
            else isinstance(value, str) and bool(value.strip())
        )
        if not valid:
            raise XingheAgentError(
                "AMAZON_PRODUCT_MASTER_INVALID",
                f"Product Master Description has an invalid {key}.",
                json_pointer=f"/analysis/product_master_description/{key}",
            )
    consistency_lock = plan.get("product_consistency_lock")
    if not isinstance(consistency_lock, Mapping) or not consistency_lock:
        raise XingheAgentError(
            "AMAZON_PRODUCT_CONSISTENCY_LOCK_INVALID",
            "Amazon planning requires a Product Consistency Lock.",
            json_pointer="/plan/product_consistency_lock",
        )
    suite_lock = plan.get("suite_cohesion_lock")
    if not isinstance(suite_lock, Mapping) or not suite_lock:
        raise XingheAgentError(
            "AMAZON_SUITE_COHESION_LOCK_INVALID",
            "Amazon planning requires a Suite Cohesion Lock.",
            json_pointer="/plan/suite_cohesion_lock",
        )
    for key in (
        "primary_palette",
        "accent_palette",
        "typography_mood",
        "icon_stroke",
        "corner_radius",
        "shadow_system",
        "lighting_system",
        "brand_motif",
        "responsive_pair_rule",
    ):
        value = suite_lock.get(key)
        if not isinstance(value, str) or not value.strip():
            raise XingheAgentError(
                "AMAZON_SUITE_COHESION_LOCK_INVALID",
                f"Suite Cohesion Lock has an invalid {key}.",
                json_pointer=f"/plan/suite_cohesion_lock/{key}",
            )
    background_systems = suite_lock.get("background_systems")
    if (
        not isinstance(background_systems, list)
        or not 2 <= len(background_systems) <= 4
        or any(not isinstance(value, str) or not value.strip() for value in background_systems)
        or len({value.strip().casefold() for value in background_systems})
        != len(background_systems)
    ):
        raise XingheAgentError(
            "AMAZON_SUITE_COHESION_LOCK_INVALID",
            "Suite Cohesion Lock requires two to four distinct background systems.",
            json_pointer="/plan/suite_cohesion_lock/background_systems",
        )
    screens = plan["screens"]
    expected = {spec.item_key: spec for spec in AMAZON_ITEM_SPECS}
    actual_keys = [screen.get("item_key") for screen in screens]
    if actual_keys != list(AMAZON_ITEM_KEYS):
        raise XingheAgentError(
            "AMAZON_ITEM_INVENTORY_INVALID",
            "Amazon planner must return the canonical 21 item keys in order.",
            json_pointer="/plan/screens",
        )
    required = (
        "asset_type",
        "final_size",
        "selling_point",
        "information_confidence",
        "visual_proof",
        "headline",
        "subcopy",
        "layout_direction",
        "source_material",
        "risk_note",
    )
    for index, screen in enumerate(screens):
        item_key = str(screen["item_key"])
        spec = expected[item_key]
        for key in required:
            value = screen.get(key)
            if not isinstance(value, str) or (key != "subcopy" and not value.strip()):
                raise XingheAgentError(
                    "AMAZON_PLAN_SCREEN_INVALID",
                    f"Amazon plan screen requires {key}.",
                    json_pointer=f"/plan/screens/{index}/{key}",
                )
        if screen["final_size"] != f"{spec.width}x{spec.height}":
            raise XingheAgentError(
                "AMAZON_TARGET_SIZE_MISMATCH",
                f"{item_key} has the wrong final_size.",
                json_pointer=f"/plan/screens/{index}/final_size",
            )
    maximum = int(plan["layout_diversity_lock"]["max_same_layout_family"])
    if maximum != 2:
        raise XingheAgentError(
            "AMAZON_LAYOUT_DIVERSITY_INVALID",
            "Amazon planning requires max_same_layout_family to be exactly 2.",
            json_pointer="/plan/layout_diversity_lock/max_same_layout_family",
        )
    selling = [screen for screen in screens if screen["item_key"] != "MAIN-01"]
    layout_counts = Counter(
        str(screen["layout_family"]).strip().casefold() for screen in selling
    )
    if layout_counts and max(layout_counts.values()) > maximum:
        raise XingheAgentError(
            "AMAZON_LAYOUT_DIVERSITY_INVALID",
            "Amazon selling images repeat layout_family too often.",
            json_pointer="/plan/screens",
        )
    approved_backgrounds = {
        value.strip().casefold() for value in background_systems
    }
    canonical_backgrounds = dict(_AMAZON_SCREEN_BACKGROUND_SYSTEMS)
    for index, screen in enumerate(screens):
        item_key = str(screen["item_key"])
        background_system = str(screen["background_system"]).strip().casefold()
        if item_key == "MAIN-01":
            if background_system != "pure-white-compliance":
                raise XingheAgentError(
                    "AMAZON_MAIN_IMAGE_INVALID",
                    "MAIN-01 background_system must be pure-white-compliance.",
                    json_pointer=f"/plan/screens/{index}/background_system",
                )
            continue
        if background_system not in approved_backgrounds:
            raise XingheAgentError(
                "AMAZON_SUITE_COHESION_INVALID",
                "Amazon selling-screen background_system is outside the Suite Cohesion Lock.",
                json_pointer=f"/plan/screens/{index}/background_system",
            )
        expected_background = canonical_backgrounds[item_key]
        if background_system != expected_background.casefold():
            raise XingheAgentError(
                "AMAZON_SUITE_BACKGROUND_ASSIGNMENT_INVALID",
                (
                    f"{item_key} background_system must be "
                    f"{expected_background}."
                ),
                json_pointer=f"/plan/screens/{index}/background_system",
            )
    by_item_key = {str(screen["item_key"]): screen for screen in screens}
    index_by_item_key = {
        str(screen["item_key"]): index for index, screen in enumerate(screens)
    }
    for pair_index in range(1, 8):
        desktop_key = f"A-DESKTOP-{pair_index:02d}"
        mobile_key = f"A-MOBILE-{pair_index:02d}"
        desktop = by_item_key[desktop_key]
        mobile = by_item_key[mobile_key]
        desktop_concept = desktop.get("responsive_concept")
        mobile_concept = mobile.get("responsive_concept")
        same_concept = (
            isinstance(desktop_concept, str)
            and bool(desktop_concept.strip())
            and isinstance(mobile_concept, str)
            and bool(mobile_concept.strip())
            and desktop_concept.strip().casefold()
            == mobile_concept.strip().casefold()
        )
        same_layout_family = (
            str(desktop["layout_family"]).strip().casefold()
            == str(mobile["layout_family"]).strip().casefold()
        )
        same_background_system = (
            str(desktop["background_system"]).strip().casefold()
            == str(mobile["background_system"]).strip().casefold()
        )
        different_subject_scale = (
            str(desktop["subject_scale"]).strip().casefold()
            != str(mobile["subject_scale"]).strip().casefold()
        )
        if not (
            same_concept
            and same_layout_family
            and same_background_system
            and different_subject_scale
        ):
            invalid_field = (
                "responsive_concept"
                if not same_concept
                else "layout_family"
                if not same_layout_family
                else "background_system"
                if not same_background_system
                else "subject_scale"
            )
            raise XingheAgentError(
                "AMAZON_RESPONSIVE_PAIR_INVALID",
                (
                    "Paired desktop and mobile A+ screens must share "
                    "responsive_concept, layout_family, and background_system, "
                    "and use different subject_scale values."
                ),
                json_pointer=(
                    f"/plan/screens/{index_by_item_key[mobile_key]}/"
                    f"{invalid_field}"
                ),
            )
    return structured


def editable_amazon_structured_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the planner object from the durable editable plan payload."""

    groups = payload.get("groups")
    pages = payload.get("pages")
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(pages, list):
        raise AdapterValidationError(
            "AMAZON_PLAN_INVALID",
            "Amazon plan requires exactly one product group and 21 pages.",
        )
    group = groups[0]
    if not isinstance(group, Mapping):
        raise AdapterValidationError(
            "AMAZON_PLAN_INVALID",
            "Amazon product-group plan must be an object.",
        )
    return {
        "analysis": group.get("analysis"),
        "plan": {
            "campaign_style_lock": group.get("campaign_style_lock"),
            "design_strength_lock": group.get("design_strength_lock"),
            "product_consistency_lock": group.get("product_consistency_lock"),
            "suite_cohesion_lock": group.get("suite_cohesion_lock"),
            "layout_diversity_lock": group.get("layout_diversity_lock"),
            "screens": pages,
        },
    }


def validate_editable_amazon_plan_payload(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from app.xinghe_agent import XingheAgentError

    try:
        validate_amazon_planner_payload(editable_amazon_structured_plan(payload))
    except (AdapterValidationError, XingheAgentError) as exc:
        return [
            {
                "field": getattr(exc, "json_pointer", None) or "plan",
                "message": str(exc),
                "code": getattr(exc, "code", "AMAZON_PLAN_INVALID"),
            }
        ]
    return []


def synchronize_confirmed_amazon_plan(
    session: Any,
    job: Any,
    plan: Any,
) -> None:
    """Apply the confirmed Product Master and 21-row plan to every JobItem."""

    from sqlalchemy import select

    from app.models import JobItemRecord
    from app.services import canonical_hash
    from app.xinghe_agent import XingheAgentError

    try:
        structured = validate_amazon_planner_payload(
            editable_amazon_structured_plan(plan.payload)
        )
    except (AdapterValidationError, XingheAgentError):
        raise
    items = session.scalars(
        select(JobItemRecord)
        .where(JobItemRecord.job_id == job.id)
        .order_by(JobItemRecord.ordinal)
        .with_for_update()
    ).all()
    if [item.item_key for item in items] != list(AMAZON_ITEM_KEYS):
        raise AdapterValidationError(
            "AMAZON_ITEM_INVENTORY_INVALID",
            "Durable Amazon items do not match the confirmed plan.",
        )
    payload = dict(plan.payload)
    resume_signature = canonical_hash(
        {
            "version": AMAZON_PLANNING_POLICY_VERSION,
            "input_signature": payload.get("input_signature"),
            "structured_plan": structured,
        }
    )
    context = {
        "schema_version": AMAZON_PLANNING_POLICY_VERSION,
        "analysis": structured["analysis"],
        "campaign_style_lock": structured["plan"]["campaign_style_lock"],
        "design_strength_lock": structured["plan"]["design_strength_lock"],
        "product_consistency_lock": structured["plan"]["product_consistency_lock"],
        "suite_cohesion_lock": structured["plan"]["suite_cohesion_lock"],
        "layout_diversity_lock": structured["plan"]["layout_diversity_lock"],
        "input_signature": payload.get("input_signature"),
        "resume_signature": resume_signature,
    }
    for item, screen in zip(items, structured["plan"]["screens"], strict=True):
        configuration = dict(item.configuration)
        configuration.update(
            {
                "workflow_version": AMAZON_PLANNING_POLICY_VERSION,
                "planning_policy_version": AMAZON_PLANNING_POLICY_VERSION,
                "resume_signature": resume_signature,
                "quality": "high",
                AMAZON_PLAN_CONFIGURATION_KEY: {**context, "screen": screen},
            }
        )
        item.configuration = configuration
        item.quality = "high"
        item.stage = "queued"
        item.state_version += 1
    payload["resume_signature"] = resume_signature
    payload["state"] = "confirmed"
    plan.payload = payload
    plan.payload_hash = canonical_hash(payload)


class AmazonVisualSuiteProvider:
    """Validate one Amazon JobItem and delegate real or fake generation.

    Contact sheets are intentionally absent from ``AMAZON_ITEM_KEYS`` and can
    never pass this adapter as a counted deliverable.
    """

    def __init__(
        self,
        delegate: Provider,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        self.delegate = delegate
        self.manifest_validator = manifest_validator or BundledSkillManifestValidator()
        self.name = delegate.name
        self.model = delegate.model
        self.pricing_version = delegate.pricing_version

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            content_hash = self.manifest_validator.validate(
                AMAZON_VISUAL_SUITE_SKILL_ID
            )
            if not isinstance(content_hash, str) or not content_hash.strip():
                raise AdapterValidationError(
                    "SKILL_MANIFEST_VALIDATION_FAILED",
                    "The Skill manifest validator did not return a content hash.",
                )
            routed_request, spec = self.prepare_request(
                request,
                content_hash=content_hash.strip(),
            )
        except SkillRuntimeError as exc:
            return rejected_result(self, exc.code, str(exc))
        except (AdapterValidationError, NewImageSkillContractError) as exc:
            return rejected_result(self, exc.code, str(exc))
        except Exception as exc:
            return rejected_result(
                self,
                "SKILL_MANIFEST_VALIDATION_FAILED",
                f"Skill manifest validation failed ({type(exc).__name__}).",
            )

        result = await self.delegate.execute(routed_request)
        if result.outcome != ProviderOutcome.SUCCEEDED:
            return result
        return self._validate_output_contract(result, spec)

    def prepare_request(
        self,
        request: ProviderRequest,
        *,
        content_hash: str,
    ) -> tuple[ProviderRequest, AmazonItemSpec]:
        if request.operation != AMAZON_VISUAL_SUITE_OPERATION:
            raise AdapterValidationError(
                "OPERATION_NOT_SUPPORTED",
                (
                    f"{AMAZON_VISUAL_SUITE_SKILL_ID} only accepts "
                    f"{AMAZON_VISUAL_SUITE_OPERATION}."
                ),
            )
        job_configuration = job_configuration_from(request.configuration)
        marketplace = job_configuration.get("marketplace", AMAZON_DEFAULT_MARKETPLACE)
        if not isinstance(marketplace, str) or marketplace not in AMAZON_MARKETPLACES:
            raise AdapterValidationError(
                "AMAZON_MARKETPLACE_UNSUPPORTED",
                f"Unsupported Amazon marketplace: {marketplace!r}.",
            )
        item_configuration = _item_configuration(request.configuration)
        item_key = _required_item_key(item_configuration)
        spec = amazon_item_spec(item_key)
        _validate_contact_sheet_semantics(item_configuration)
        _validate_requested_dimensions(item_configuration, spec)
        _validate_group_semantics(item_configuration, spec)

        input_configuration = _job_input_configuration(request.configuration)
        source_assets = _amazon_source_assets(input_configuration)
        item_ordinal = AMAZON_ITEM_KEYS.index(spec.item_key)
        plan_context = _amazon_plan_context(item_configuration, spec)
        prompt_input = _amazon_prompt_input(job_configuration, spec, plan_context)
        aspect_ratio = _aspect_ratio(spec.width, spec.height)
        adapter_configuration = {
            "schema_version": AMAZON_ADAPTER_CONTRACT_VERSION,
            "skill_id": AMAZON_VISUAL_SUITE_SKILL_ID,
            "skill_content_hash": content_hash,
            "operation": AMAZON_VISUAL_SUITE_OPERATION,
            "item_key": spec.item_key,
            "item_ordinal": item_ordinal,
            "source_assets": source_assets,
            "target": {
                "aspect_ratio": aspect_ratio,
                "width": spec.width,
                "height": spec.height,
                "quality": "high",
                "output_format": "jpeg",
                "fit": _safe_fit(spec),
            },
            "prompt_input": prompt_input,
        }
        audit_configuration = {
            "expected_item_count": AMAZON_EXPECTED_ITEM_COUNT,
            "canonical_item_keys": AMAZON_ITEM_KEYS,
            "contact_sheet": False,
            "item": {
                "item_key": spec.item_key,
                "delegate_item_key": spec.item_key,
                "group": spec.group,
                "group_ordinal": spec.group_ordinal,
                "target_width": spec.width,
                "target_height": spec.height,
                "deliverable_counted": True,
                "contact_sheet": False,
                "task": _amazon_task_contract(spec),
                "plan_resume_signature": plan_context["resume_signature"],
            },
        }
        return (
            replace(
                request,
                configuration={
                    **request.configuration,
                    SKILL_ADAPTER_CONFIGURATION_KEY: adapter_configuration,
                    AMAZON_AUDIT_CONFIGURATION_KEY: audit_configuration,
                },
            ),
            spec,
        )

    def _validate_output_contract(
        self,
        result: ProviderResult,
        spec: AmazonItemSpec,
    ) -> ProviderResult:
        artifact = result.persisted_artifact or result.artifact
        if artifact is None:
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="AMAZON_OUTPUT_ARTIFACT_MISSING",
                error_message=(
                    f"{spec.item_key} succeeded without a deliverable artifact."
                ),
                retryable=False,
                artifact=None,
                persisted_artifact=None,
            )
        if (artifact.width, artifact.height) != (spec.width, spec.height):
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="AMAZON_OUTPUT_DIMENSIONS_INVALID",
                error_message=(
                    f"{spec.item_key} requires {spec.width}x{spec.height}, got "
                    f"{artifact.width}x{artifact.height}."
                ),
                retryable=False,
                artifact=None,
                persisted_artifact=None,
            )
        if artifact.content_type.lower() != "image/jpeg":
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="AMAZON_OUTPUT_FORMAT_INVALID",
                error_message=f"{spec.item_key} requires an Amazon-ready JPEG export.",
                retryable=False,
                artifact=None,
                persisted_artifact=None,
            )
        return result


def _item_configuration(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = configuration.get("item")
    if nested is None:
        return configuration
    if not isinstance(nested, Mapping):
        raise AdapterValidationError(
            "AMAZON_ITEM_CONFIGURATION_INVALID",
            "Amazon item configuration must be an object.",
        )
    return nested


def _job_input_configuration(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    job = configuration.get("job")
    if job is None:
        return {}
    if not isinstance(job, Mapping):
        raise AdapterValidationError(
            "JOB_CONFIGURATION_INVALID",
            "Provider request job configuration must be an object.",
        )
    value = job.get("input")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AdapterValidationError(
            "JOB_INPUT_INVALID",
            "Provider request job input must be an object.",
        )
    return value


def _amazon_source_assets(
    input_configuration: Mapping[str, Any],
) -> list[dict[str, str]]:
    white_background = require_asset_ids(
        input_configuration,
        "white_background_product_asset_ids",
    )
    detail = validate_optional_asset_ids(input_configuration, "detail_asset_ids")
    package = validate_optional_asset_ids(input_configuration, "package_asset_ids")
    scene = validate_optional_asset_ids(input_configuration, "scene_asset_ids")
    brand = validate_optional_asset_ids(input_configuration, "brand_asset_ids")
    return role_labelled_assets(
        ("white_background_product", white_background),
        ("product_detail", detail),
        ("package_reference", package),
        ("scene_reference", scene),
        ("brand_reference", brand),
    )


def _amazon_prompt_input(
    job_configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
    plan_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile only the explicit Amazon prompt whitelist."""

    listing_title = optional_string(job_configuration, "listing_title")
    bullet_points = optional_string_list(job_configuration, "bullet_points")
    product_information = [value for value in (listing_title, *bullet_points) if value]
    screen = plan_context["screen"]
    return compact_prompt_input(
        {
            "marketplace": optional_string(
                job_configuration,
                "marketplace",
                default=AMAZON_DEFAULT_MARKETPLACE,
            ),
            "product_name": optional_string(job_configuration, "product_name"),
            "product_information": product_information,
            "color_palette": optional_string_list(job_configuration, "brand_colors"),
            "language": optional_string(job_configuration, "language", default="en-US"),
            "composition": spec.group,
            "creative_direction": [
                f"Asset type: {spec.asset_type}",
                f"Layout direction: {screen['layout_direction']}",
                f"Layout family: {screen['layout_family']}",
                f"Camera angle: {screen['camera_angle']}",
                f"Product position: {screen['product_position']}",
                f"Background system: {screen['background_system']}",
                f"Prop strategy: {screen['prop_strategy']}",
                f"Copy density: {screen['copy_density']}",
                *(
                    [f"Responsive concept: {screen['responsive_concept']}"]
                    if spec.group in {"a_desktop", "a_mobile"}
                    and isinstance(screen.get("responsive_concept"), str)
                    and screen["responsive_concept"].strip()
                    else []
                ),
            ],
            "copy_requirements": [
                f"Headline: {screen['headline']}",
                f"Subcopy: {screen['subcopy']}",
            ],
            "reference_guidance": [
                "Product Master Description: " + _stable_json(
                    plan_context["analysis"]["product_master_description"]
                ),
                "Product Consistency Anchors: " + _stable_json(
                    plan_context["analysis"]["product_consistency_anchors"]
                ),
                "Product Consistency Lock: " + _stable_json(
                    plan_context["product_consistency_lock"]
                ),
                "Campaign Style Lock: " + _stable_json(
                    plan_context["campaign_style_lock"]
                ),
                "Design Strength Lock: " + _stable_json(
                    plan_context["design_strength_lock"]
                ),
                *(
                    [
                        "Suite Cohesion Lock: "
                        + _stable_json(plan_context["suite_cohesion_lock"])
                    ]
                    if isinstance(plan_context.get("suite_cohesion_lock"), Mapping)
                    and plan_context["suite_cohesion_lock"]
                    else []
                ),
                "Layout Diversity Lock: " + _stable_json(
                    plan_context["layout_diversity_lock"]
                ),
                f"Buyer question: {screen['buyer_question']}",
                f"Selling point: {screen['selling_point']}",
                f"Information confidence: {screen['information_confidence']}",
                f"Visual proof: {screen['visual_proof']}",
                f"Source material: {screen['source_material']}",
            ],
            "negative_constraints": [
                _GLOBAL_RISK_GUARD,
                spec.risk_note,
                str(screen["risk_note"]),
            ],
            "image_count": 1,
        }
    )


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _amazon_plan_context(
    item_configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> Mapping[str, Any]:
    value = item_configuration.get(AMAZON_PLAN_CONFIGURATION_KEY)
    if not isinstance(value, Mapping):
        raise AdapterValidationError(
            "AMAZON_PLAN_CONTEXT_MISSING",
            "Amazon generation requires a confirmed persisted plan context.",
        )
    required_mappings = [
        "analysis",
        "campaign_style_lock",
        "design_strength_lock",
        "product_consistency_lock",
        "layout_diversity_lock",
        "screen",
    ]
    if value.get("schema_version") == AMAZON_PLANNING_POLICY_VERSION:
        required_mappings.append("suite_cohesion_lock")
    for key in required_mappings:
        if not isinstance(value.get(key), Mapping) or not value[key]:
            raise AdapterValidationError(
                "AMAZON_PLAN_CONTEXT_MISSING",
                f"Amazon confirmed plan context is missing {key}.",
            )
    resume_signature = value.get("resume_signature")
    if not isinstance(resume_signature, str) or len(resume_signature) != 64:
        raise AdapterValidationError(
            "AMAZON_PLAN_CONTEXT_MISSING",
            "Amazon confirmed plan context has no valid resume signature.",
        )
    screen = value["screen"]
    if screen.get("item_key") != spec.item_key:
        raise AdapterValidationError(
            "AMAZON_PLAN_ITEM_MISMATCH",
            "Amazon confirmed plan screen does not match the durable item.",
        )
    analysis = value["analysis"]
    if not isinstance(analysis.get("product_master_description"), Mapping):
        raise AdapterValidationError(
            "AMAZON_PLAN_CONTEXT_MISSING",
            "Amazon confirmed plan has no Product Master Description.",
        )
    if not isinstance(analysis.get("product_consistency_anchors"), Mapping):
        raise AdapterValidationError(
            "AMAZON_PLAN_CONTEXT_MISSING",
            "Amazon confirmed plan has no Product Consistency Anchors.",
        )
    return value


def _amazon_task_contract(spec: AmazonItemSpec) -> dict[str, str]:
    """Return the stable, authoritative task row for exactly one deliverable."""

    return {
        "id": spec.item_key,
        "asset_type": spec.asset_type,
        "final_size": f"{spec.width}x{spec.height}",
        "buyer_question": spec.buyer_question,
        "selling_point": spec.selling_point,
        "information_confidence": _CONFIDENCE_RULE,
        "visual_proof": spec.visual_proof,
        "headline": spec.headline,
        "subcopy": spec.subcopy,
        "layout_direction": spec.layout_direction,
        "source_material": spec.source_material,
        "risk_note": spec.risk_note,
    }


def _safe_fit(spec: AmazonItemSpec) -> str:
    """Choose a no-loss final-size strategy for each Amazon asset group."""

    if spec.group == "main":
        return "pad"
    return "contain"


def _aspect_ratio(width: int, height: int) -> str:
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _required_item_key(configuration: Mapping[str, Any]) -> str:
    value = configuration.get("item_key")
    if not isinstance(value, str) or not value.strip():
        raise AdapterValidationError(
            "AMAZON_ITEM_KEY_MISSING",
            "Amazon item configuration requires item_key.",
        )
    return value.strip()


def _validate_contact_sheet_semantics(configuration: Mapping[str, Any]) -> None:
    if configuration.get("contact_sheet") is True:
        raise AdapterValidationError(
            "AMAZON_CONTACT_SHEET_NOT_DELIVERABLE",
            "Contact sheets cannot be counted among the 21 Amazon deliverables.",
        )


def _validate_group_semantics(
    configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> None:
    value = configuration.get("group")
    if value is None:
        return
    if str(value).strip().lower() != spec.group:
        raise AdapterValidationError(
            "AMAZON_ITEM_GROUP_MISMATCH",
            f"{spec.item_key} belongs to group {spec.group}.",
        )


def _validate_requested_dimensions(
    configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> None:
    width, height = _requested_dimensions(configuration)
    if width is None or height is None:
        raise AdapterValidationError(
            "AMAZON_TARGET_SIZE_MISSING",
            f"{spec.item_key} requires an explicit target size.",
        )
    if (width, height) != (spec.width, spec.height):
        raise AdapterValidationError(
            "AMAZON_TARGET_SIZE_MISMATCH",
            (
                f"{spec.item_key} requires {spec.width}x{spec.height}, got "
                f"{width}x{height}."
            ),
        )


def _requested_dimensions(
    configuration: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    width = configuration.get("target_width")
    height = configuration.get("target_height")
    target_size = configuration.get("target_size")
    if isinstance(target_size, Mapping):
        width = target_size.get("width", width)
        height = target_size.get("height", height)
    elif isinstance(target_size, str) and "x" in target_size.lower():
        raw_width, raw_height = target_size.lower().split("x", maxsplit=1)
        width, height = raw_width.strip(), raw_height.strip()
    return _positive_int_or_none(width), _positive_int_or_none(height)


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed > 0 else None
