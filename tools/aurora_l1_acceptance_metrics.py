#!/usr/bin/env python3
"""Compute the handover doc section 5 acceptance metrics for Aurora audits.

Stdlib only, so it can be piped straight into a production container:

    ssh ubuntu@<host> 'docker exec -i polaris-production-worker-1 python3 -' \
        < tools/aurora_l1_acceptance_metrics.py

Metrics (all defined per generated page, then aggregated per job):

* first_pass_rate    -- pages whose first audit reports no material failure
* copy_rejections    -- material rejections on copy/fact checks
* misjudged_rate     -- of those, the share whose rejected claim is in fact
                        authorized by the page contract or the user fact pool
* repair_rate        -- pages that entered the one-repair loop
* reaudit_pass_rate  -- pages whose post-repair audit passes
* duration_seconds   -- job wall clock, taken from the jobs table (see --psql)

The "misjudged" predicate mirrors the evidence in section 2.5: a copy rejection
is a false positive when the wording it calls unsupported is already present in
the page's compiled claim set or in the user's own verified fact pool.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("/app/.data/aurora-main-image")

# Copy/fact checks.  The narrow set is what section 2.5 counted; the wide set
# adds the two claim-to-pixel checks that are also driven by copy wording.
NARROW_COPY_CHECKS = frozenset({"factual_copy_match", "no_unsupported_claim"})
WIDE_COPY_CHECKS = NARROW_COPY_CHECKS | {
    "text_not_substituting_for_visual_proof",
    "claim_to_evidence_relation_clear",
}

FACT_POOL_KEYS = (
    "verified_selling_points",
    "verified_attributes",
    "verified_scenes",
    "verified_offers",
    "verified_service_or_trust_facts",
    "user_provided_display_facts",
)

CLAIM_CONTRACT_KEYS = (
    "source_claim",
    "support_source_segments",
    "claim_bundle",
    "supporting_claims",
    "primary_claim",
)

_MIN_CLAIM_CHARS = 2


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_strings(item))
        return result
    return []


def _page_contract(page_dir: Path) -> dict[str, Any]:
    for name in ("generation-request.json", "repair-generation-request.json"):
        payload = _load(page_dir / name)
        if isinstance(payload, dict) and isinstance(payload.get("page_contract"), dict):
            return payload["page_contract"]
    return {}


def _authorized_claims(page_dir: Path, fact_pool: dict[str, Any]) -> set[str]:
    """Every wording the user or the compiled plan authorizes for this page."""

    contract = _page_contract(page_dir)
    copy_contract = _as_mapping(contract.get("display_copy_contract"))
    claims: list[str] = []
    for key in CLAIM_CONTRACT_KEYS:
        claims.extend(_strings(contract.get(key)))
        claims.extend(_strings(copy_contract.get(key)))
    for key in FACT_POOL_KEYS:
        claims.extend(_strings(fact_pool.get(key)))
    return {
        claim
        for claim in claims
        if len(re.sub(r"\s+", "", claim)) >= _MIN_CLAIM_CHARS
    }


def _fact_pool(workspace: Path) -> dict[str, Any]:
    session = _as_mapping(_load(workspace / "session.json"))
    product = _as_mapping(_as_mapping(session.get("raw_input")).get("product"))
    return product


def _attempt_dir(page_dir: Path) -> Path | None:
    attempts = sorted(
        (item for item in page_dir.iterdir() if item.is_dir()),
        key=lambda item: item.name,
    ) if page_dir.is_dir() else []
    return attempts[-1] if attempts else None


def _material_failures(judgment: dict[str, Any]) -> list[dict[str, Any]]:
    deficiencies = judgment.get("all_material_deficiencies")
    if isinstance(deficiencies, list):
        return [item for item in deficiencies if isinstance(item, dict)]
    # Fall back to the checks list when the reviewer omitted the rollup.
    failures = []
    for check in judgment.get("checks") or []:
        if not isinstance(check, dict):
            continue
        if check.get("material") and not check.get("passed"):
            failures.append(
                {
                    "check": check.get("name"),
                    "visible_problem": check.get("observed_evidence"),
                }
            )
    return failures


def _deficiency_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("visible_problem", "root_cause", "required_change")
    )


def _misjudged(item: dict[str, Any], authorized: set[str]) -> list[str]:
    """Authorized wordings the rejection wrongly calls unsupported."""

    text = _deficiency_text(item)
    return sorted(claim for claim in authorized if claim in text)


def collect_job(workspace: Path) -> dict[str, Any]:
    fact_pool = _fact_pool(workspace)
    pages: list[dict[str, Any]] = []
    parallel_root = workspace / "parallel-v20"
    page_dirs = (
        sorted(item for item in parallel_root.iterdir() if item.is_dir())
        if parallel_root.is_dir()
        else []
    )
    if not page_dirs:
        # Sequential v0.1.17 layout: a single workspace, one judgment per attempt.
        page_dirs = [workspace]
    for page_dir in page_dirs:
        attempt = _attempt_dir(page_dir)
        if attempt is None:
            continue
        judgment_1 = _as_mapping(_load(attempt / "judgment-1.json"))
        judgment_2 = _as_mapping(_load(attempt / "judgment-2.json"))
        repair = _as_mapping(_load(attempt / "repair.json"))
        if not judgment_1:
            pages.append(
                {
                    "page": page_dir.name,
                    "audited": False,
                    "repair_triggered": bool(repair),
                }
            )
            continue
        authorized = _authorized_claims(page_dir, fact_pool)
        failures = _material_failures(judgment_1)
        copy_failures = [
            item
            for item in failures
            if str(item.get("check") or "") in WIDE_COPY_CHECKS
        ]
        narrow_failures = [
            item
            for item in copy_failures
            if str(item.get("check") or "") in NARROW_COPY_CHECKS
        ]
        misjudged = [
            {"check": item.get("check"), "authorized_claims": found}
            for item in copy_failures
            for found in [_misjudged(item, authorized)]
            if found
        ]
        narrow_misjudged = [
            item
            for item in misjudged
            if str(item.get("check") or "") in NARROW_COPY_CHECKS
        ]
        pages.append(
            {
                "page": page_dir.name,
                "audited": True,
                "first_pass": not failures,
                "material_failures": sorted(
                    str(item.get("check") or "") for item in failures
                ),
                "copy_failures": len(copy_failures),
                "narrow_copy_failures": len(narrow_failures),
                "misjudged": len(misjudged),
                "narrow_misjudged": len(narrow_misjudged),
                "misjudged_detail": misjudged,
                "repair_triggered": bool(repair),
                "repair_scope": repair.get("scope"),
                "reaudited": bool(judgment_2),
                "reaudit_pass": (
                    not _material_failures(judgment_2) if judgment_2 else None
                ),
            }
        )
    audited = [page for page in pages if page.get("audited")]
    repaired = [page for page in audited if page.get("repair_triggered")]
    reaudited = [page for page in audited if page.get("reaudited")]
    copy_total = sum(page["copy_failures"] for page in audited)
    narrow_total = sum(page["narrow_copy_failures"] for page in audited)
    misjudged_total = sum(page["misjudged"] for page in audited)
    narrow_misjudged_total = sum(page["narrow_misjudged"] for page in audited)

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "job": workspace.name,
        "fact_pool_size": sum(
            len(_strings(fact_pool.get(key))) for key in FACT_POOL_KEYS
        ),
        "pages_total": len(pages),
        "pages_audited": len(audited),
        "first_pass": sum(1 for page in audited if page.get("first_pass")),
        "first_pass_rate": rate(
            sum(1 for page in audited if page.get("first_pass")), len(audited)
        ),
        "copy_failures_wide": copy_total,
        "copy_failures_narrow": narrow_total,
        "copy_misjudged": misjudged_total,
        "copy_misjudged_rate_wide": rate(misjudged_total, copy_total),
        "copy_misjudged_narrow": narrow_misjudged_total,
        "copy_misjudged_rate_narrow": rate(narrow_misjudged_total, narrow_total),
        "repair_triggered": len(repaired),
        "repair_rate": rate(len(repaired), len(audited)),
        "reaudited": len(reaudited),
        "reaudit_pass": sum(1 for page in reaudited if page.get("reaudit_pass")),
        "reaudit_pass_rate": rate(
            sum(1 for page in reaudited if page.get("reaudit_pass")),
            len(reaudited),
        ),
        "pages": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--job", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="emit raw JSON only")
    args = parser.parse_args()

    root = Path(args.root)
    if args.job:
        workspaces = [root / job for job in args.job]
    else:
        workspaces = sorted(item for item in root.iterdir() if item.is_dir())
    workspaces = [item for item in workspaces if item.is_dir()]
    if not workspaces:
        print(f"no job workspaces under {root}", file=sys.stderr)
        return 1

    results = [collect_job(item) for item in workspaces]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    header = (
        f"{'job':<34} {'pg':>3} {'pass1':>6} {'copy':>5} {'mis':>5} "
        f"{'mis%':>6} {'rep':>5} {'rep%':>6} {'re-pass%':>9}"
    )
    print(header)
    print("-" * len(header))
    for item in results:
        def pct(value: float | None) -> str:
            return "-" if value is None else f"{value * 100:.1f}"

        print(
            f"{item['job'][:34]:<34} {item['pages_audited']:>3} "
            f"{item['first_pass']:>6} {item['copy_failures_wide']:>5} "
            f"{item['copy_misjudged']:>5} {pct(item['copy_misjudged_rate_wide']):>6} "
            f"{item['repair_triggered']:>5} {pct(item['repair_rate']):>6} "
            f"{pct(item['reaudit_pass_rate']):>9}"
        )
    audited = sum(item["pages_audited"] for item in results)
    first_pass = sum(item["first_pass"] for item in results)
    copy_total = sum(item["copy_failures_wide"] for item in results)
    misjudged = sum(item["copy_misjudged"] for item in results)
    repaired = sum(item["repair_triggered"] for item in results)
    reaudited = sum(item["reaudited"] for item in results)
    reaudit_pass = sum(item["reaudit_pass"] for item in results)
    print("-" * len(header))
    print(
        f"{'TOTAL':<34} {audited:>3} {first_pass:>6} {copy_total:>5} "
        f"{misjudged:>5} "
        f"{(100 * misjudged / copy_total if copy_total else 0):>6.1f} "
        f"{repaired:>5} "
        f"{(100 * repaired / audited if audited else 0):>6.1f} "
        f"{(100 * reaudit_pass / reaudited if reaudited else 0):>9.1f}"
    )
    print()
    narrow_failures = sum(item["copy_failures_narrow"] for item in results)
    narrow_misjudged = sum(item["copy_misjudged_narrow"] for item in results)
    print(
        "narrow copy checks only "
        f"({', '.join(sorted(NARROW_COPY_CHECKS))}): "
        f"{narrow_misjudged}/{narrow_failures} misjudged = "
        f"{(100 * narrow_misjudged / narrow_failures if narrow_failures else 0):.1f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
