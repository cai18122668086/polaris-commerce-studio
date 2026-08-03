"""Independent manifest-gated adapter for the Amazon 21-image suite."""

# The authoritative 21-row task table intentionally keeps buyer-facing copy
# visible beside each stable item key; wrapping those values would obscure review.
# ruff: noqa: E501

from __future__ import annotations

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
        prompt_input = _amazon_prompt_input(job_configuration, spec)
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
) -> dict[str, Any]:
    """Compile only the explicit Amazon prompt whitelist."""

    listing_title = optional_string(job_configuration, "listing_title")
    bullet_points = optional_string_list(job_configuration, "bullet_points")
    product_information = [value for value in (listing_title, *bullet_points) if value]
    task = _amazon_task_contract(spec)
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
                f"Layout direction: {spec.layout_direction}",
            ],
            "copy_requirements": [
                f"Headline: {spec.headline}",
                f"Subcopy: {spec.subcopy}",
            ],
            "reference_guidance": [
                f"Buyer question: {task['buyer_question']}",
                f"Selling point: {task['selling_point']}",
                f"Information confidence: {task['information_confidence']}",
                f"Visual proof: {task['visual_proof']}",
                f"Source material: {task['source_material']}",
            ],
            "negative_constraints": [
                _GLOBAL_RISK_GUARD,
                spec.risk_note,
            ],
            "image_count": 1,
        }
    )


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
