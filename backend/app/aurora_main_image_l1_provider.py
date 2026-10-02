"""L1 rubric channel for the Aurora domestic six-image audit.

The shipped :class:`~app.aurora_main_image_provider.AuroraMainImageProvider`
audits every generated page with the frozen ``_AUDIT_SYSTEM_PROMPT``.  That
prompt restates the page contract but never carries the Skill's own pixel-audit
rubric, and the reviewer is never told which claims the user actually supplied.
The measured result is over-rejection: legitimate user facts are failed as
unsupported claims and every page enters the repair loop.

This module adds a *shadow* channel that keeps generation, planning, harness
state and persistence byte-identical, and changes only what the reviewer sees:

1. the audit system prompt gains the full text of the Skill's
   ``references/visual-audit.md`` rubric, and
2. the audit contract gains an ``authorized_claims`` block built from the page's
   compiled display-copy contract plus the user's own fact pool.

The channel is selected by ``aurora_l1_rubric_enabled`` and is off by default,
so the shipped behaviour is untouched until an operator flips the switch for a
measured shadow run.

Deliberately out of scope: no new Skill source, no new JobType, no DB
migration, and no edit to ``backend/skill_sources/``.  L1 changes *which prompt
is sent*, not *which Skill is used*.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from .aurora_main_image_provider import (
    _AUDIT_SYSTEM_PROMPT,
    AuroraMainImageProvider,
)
from .aurora_main_image_runtime import AuroraHarnessRunner
from .config import default_aurora_v20_skill_root
from .provider import ProviderRequest
from .storage import ImageStorage
from .xinghe_agent import XingheGateway

logger = logging.getLogger(__name__)

#: Marker written into the audit contract so a stored or logged request proves
#: which channel produced it.  The reviewer ignores unknown contract fields.
AUDIT_CHANNEL = "l1_rubric"

#: Rubric shipped by the v2.0 Skill tree.  Read at most once per provider.
_VISUAL_AUDIT_RUBRIC_RELATIVE = Path("references") / "visual-audit.md"

#: The shipped prompt tells the reviewer to compare source references *only*
#: for product identity.  The Skill rubric says the opposite for claims: clearly
#: readable copy inside a user-provided same-product image is itself an
#: authorized fact.  Left uncorrected the two instructions contradict each
#: other, so L1 rewrites that one sentence.  The replacement is applied to a
#: whitespace-flattened copy so it cannot silently miss on re-wrapping.
_REFERENCE_CLAUSE_SHIPPED = (
    "Compare original references only for product identity; never treat a "
    "generated image or a receipt as identity proof."
)
_REFERENCE_CLAUSE_L1 = (
    "Compare original references for product identity, and treat explicit user "
    "text and clearly readable copy inside user-provided same-product images as "
    "authorized facts; never treat a generated image or a receipt as identity "
    "proof."
)

_RUBRIC_HEADER = (
    "The rubric below is this Skill's own pixel-audit standard. It is "
    "authoritative for how to judge the candidate and overrides any generic "
    "review habit. Apply it together with the audit contract supplied as the "
    "user message."
)

#: ``raw_input.product`` fields that make up the user's supplied fact pool.
_FACT_POOL_KEYS = (
    "verified_selling_points",
    "verified_attributes",
    "verified_scenes",
    "verified_offers",
    "verified_service_or_trust_facts",
    "user_provided_display_facts",
)

_AUTHORITY_RULE = (
    "These are user-supplied facts. They are eligible display facts without a "
    "second verification request. Their lack of certificates, reports or links "
    "is NOT a defect and never triggers repair. Only fail no_unsupported_claim "
    "when the page adds a factual proposition absent from this list or "
    "materially strengthens one."
)

#: Bound the per-process fact-pool cache; the pool never changes after planning.
_FACT_POOL_CACHE_LIMIT = 64


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_text_list(value: Any) -> list[str]:
    """Keep only non-empty strings, preserving order and dropping duplicates."""

    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _flatten_whitespace(text: str) -> str:
    return " ".join(text.split())


class AuroraMainImageL1Provider(AuroraMainImageProvider):
    """Shadow channel that audits with the Skill rubric and the user fact pool.

    ``AuroraMainImageProvider`` is instantiated as a concrete class in
    ``execution.build_fake_coordinator``, so this must be a real subclass that
    the coordinator constructs explicitly.  Only the two audit hooks differ;
    everything else is inherited unchanged.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        storage: ImageStorage,
        *,
        harness: AuroraHarnessRunner | None = None,
        work_root: Path | None = None,
        execution_mode: str = "sequential_v017",
    ) -> None:
        super().__init__(
            session_factory,
            gateway,
            storage,
            harness=harness,
            work_root=work_root,
            execution_mode=execution_mode,
        )
        self._fact_pool_cache: dict[str, dict[str, Any]] = {}
        self._l1_system_prompt: str | None = None

    # --- hook 1: audit system prompt ---------------------------------------
    def _audit_system_prompt(self) -> str:
        if self._l1_system_prompt is None:
            self._l1_system_prompt = self._compose_l1_system_prompt()
        return self._l1_system_prompt

    def _compose_l1_system_prompt(self) -> str:
        base = _flatten_whitespace(_AUDIT_SYSTEM_PROMPT)
        if _REFERENCE_CLAUSE_SHIPPED in base:
            base = base.replace(_REFERENCE_CLAUSE_SHIPPED, _REFERENCE_CLAUSE_L1)
        else:
            # Do not fail the audit: the rubric below states the same authority
            # rule, so the channel still behaves as intended.  Surface it so a
            # drifting base prompt gets noticed instead of silently shipping
            # contradictory instructions.
            logger.warning(
                "Aurora L1 rubric: reference-authority clause not found in the "
                "base audit prompt; shipping the rubric without that correction."
            )
        return "\n\n".join((base, _RUBRIC_HEADER, self._visual_audit_rubric()))

    def _visual_audit_rubric(self) -> str:
        """Read the Skill's own rubric.  Fail loud: L1 must not silently
        degrade into a baseline run that is then reported as an L1 result."""

        rubric_path = default_aurora_v20_skill_root() / _VISUAL_AUDIT_RUBRIC_RELATIVE
        try:
            rubric = rubric_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Aurora L1 rubric is unreadable at {rubric_path}: {exc}"
            ) from exc
        if not rubric:
            raise RuntimeError(f"Aurora L1 rubric is empty at {rubric_path}")
        return rubric

    # --- hook 2: audit contract extras -------------------------------------
    def _audit_contract_extras(
        self,
        request: ProviderRequest,
        generation_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        page_contract = _as_mapping(generation_request.get("page_contract"))
        copy_contract = _as_mapping(page_contract.get("display_copy_contract"))
        product = self._authorized_product_facts(request.job_id)
        return {
            "audit_channel": AUDIT_CHANNEL,
            "authorized_claims": {
                "page_source_claim": copy_contract.get("source_claim"),
                "page_support_segments": _as_text_list(
                    copy_contract.get("support_source_segments")
                ),
                "campaign_fact_pool": {
                    key: _as_text_list(product.get(key))
                    for key in _FACT_POOL_KEYS
                },
                "authority_rule": _AUTHORITY_RULE,
            },
        }

    def _authorized_product_facts(self, job_id: str) -> dict[str, Any]:
        """Return ``raw_input.product`` from the job's durable Harness session.

        The fact pool only exists in ``session.json``; the compiled page
        contract carries just the claims that page uses.  A missing or
        unreadable session degrades to an empty pool rather than failing the
        audit, because the page contract still authorizes the page's own copy.
        """

        cached = self._fact_pool_cache.get(job_id)
        if cached is not None:
            return cached
        facts: dict[str, Any] = {}
        try:
            session_path = self._workspace(job_id) / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "Aurora L1 fact pool unreadable for %s: %s", job_id, exc
            )
        else:
            product = _as_mapping(_as_mapping(session).get("raw_input")).get(
                "product"
            )
            if isinstance(product, Mapping):
                facts = dict(product)
        if len(self._fact_pool_cache) >= _FACT_POOL_CACHE_LIMIT:
            self._fact_pool_cache.clear()
        self._fact_pool_cache[job_id] = facts
        return facts
