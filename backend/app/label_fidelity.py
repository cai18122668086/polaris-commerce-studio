"""Product-label fidelity gate for generated commerce pages.

The full page audits ask one vision call to judge dozens of things at once and
show it the expected label text.  On the 2026-11-25 acceptance run that let
small label typos through (精华身体乳 for 精光身体乳, 改善颜色不均 for
改善顽固色沉, 浮光瓶子香 for 浮光栀子香): the reviewer echoed the reference
wording instead of reading the pixels.

This gate separates reading from judging:

* the reference label is transcribed once per job and cached;
* each generated page is read *blind* (the expected text is never sent) from
  overlapping full-resolution tiles, so fine print stays legible;
* the comparison is done here, character by character, in code.

The caller decides what to do with a mismatch (one targeted label repair, then
deliver the better candidate and disclose the residual).
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import fcntl
import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageOps, UnidentifiedImageError

if TYPE_CHECKING:
    from .xinghe_agent import PlannerCallResult, SourceImage, XingheGateway

logger = logging.getLogger(__name__)

GATE_VERSION = "label-fidelity-v1"
READ_PROFILE = "label_fidelity_read"
REFERENCE_PROFILE = "label_fidelity_reference"
PROFILES = frozenset({READ_PROFILE, REFERENCE_PROFILE})
MAX_COMPLETION_TOKENS = 4000
# The primary compatible vision endpoint rejects chat requests with five or
# more images, so a page is read from exactly four overlapping tiles.
TILE_GRID = 2
TILE_OVERLAP = 1.35
TILE_MAX_EDGE = 1024

READ_SYSTEM_PROMPT = (
    "You read text in images character by character, exactly as the pixels "
    "show. Return JSON only."
)
REFERENCE_SYSTEM_PROMPT = (
    "You transcribe text printed on a physical product, character by "
    "character. Return JSON only."
)
READ_PROMPT = (
    "The images are four overlapping zoomed tiles (left-to-right, top-to-bottom) "
    "of ONE generated e-commerce image; the same text may appear in two tiles, "
    "report it once. Find every instance of the physical product (bottle, jar, "
    "tube, box, bag...). For each instance whose printed text is legible, "
    "transcribe every line printed ON that product, top to bottom, exactly as "
    "the pixels show, character by character. Do not correct anything, do not "
    "use brand knowledge and do not guess what the label should say. Write ? "
    "for a single unreadable character; omit lines that are too small, blurred "
    "or occluded to read. Write Chinese characters in Simplified form unless "
    "the pixels clearly show a different character. Then list every other text "
    "line in the image that is NOT printed on a product (headlines, badges, "
    "callouts, captions)."
)
REFERENCE_PROMPT = (
    "The images are overlapping zoomed tiles (left-to-right, top-to-bottom) of "
    "the original product reference photo. Transcribe every line of text that "
    "is physically printed on the product itself (label, package, cap, collar). "
    "Exclude poster headlines, badges, callouts, icon captions and any text "
    "that is not printed on the product. One entry per printed line, top to "
    "bottom, exactly as printed, keeping punctuation such as ·. Do not correct "
    "or normalise anything. Write Chinese characters in Simplified form."
)

_LINES = {"type": "array", "items": {"type": "string"}}
_READ_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"label_lines": _LINES},
                "required": ["label_lines"],
            },
        },
        "other_text_lines": _LINES,
    },
    "required": ["products", "other_text_lines"],
}
_REFERENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"label_lines": _LINES},
    "required": ["label_lines"],
}


def gate_enabled() -> bool:
    """Operators can switch the gate off without a deploy (default on)."""

    value = os.environ.get("POLARIS_LABEL_FIDELITY_GATE_ENABLED", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def response_format(profile: str) -> dict[str, Any]:
    schema = _READ_SCHEMA if profile == READ_PROFILE else _REFERENCE_SCHEMA
    return {
        "type": "json_schema",
        "json_schema": {"name": profile, "strict": True, "schema": schema},
    }


def prompt(profile: str) -> str:
    return READ_PROMPT if profile == READ_PROFILE else REFERENCE_PROMPT


def fake_payload(profile: str) -> dict[str, Any]:
    """Deterministic offline answer: a legible, unchanged label."""

    if profile == READ_PROFILE:
        return {
            "products": [{"label_lines": ["OFFLINE LABEL"]}],
            "other_text_lines": [],
        }
    return {"label_lines": ["OFFLINE LABEL"]}


# --------------------------------------------------------------------------
# Comparison (pure, deterministic)
# --------------------------------------------------------------------------

_DOTS = str.maketrans({c: "·" for c in "•・‧∙⋅･‧·"})
_SPACE = re.compile(r"\s+")


@cache
def _traditional_to_simplified() -> dict[str, str]:
    path = Path(__file__).with_name("data") / "label_script_variants.json"
    try:
        pairs = str(json.loads(path.read_text(encoding="utf-8"))["pairs"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("label script variant table unavailable")
        return {}
    return {pairs[index]: pairs[index + 1] for index in range(0, len(pairs) - 1, 2)}


def normalize_line(text: object) -> str:
    """Canonical form for char-exact comparison.

    Width/compatibility forms, whitespace, middle-dot variants and Latin case
    are presentation, not wording.  A Traditional glyph is folded to its
    Simplified form (readers sometimes answer 頑 for a printed 顽); a different
    character stays different (顏 folds to 颜, which still differs from 顽).
    """

    value = unicodedata.normalize("NFKC", str(text or ""))
    value = _SPACE.sub("", value).translate(_DOTS).casefold()
    table = _traditional_to_simplified()
    return "".join(table.get(char, char) for char in value)


@dataclass(frozen=True)
class LabelMismatch:
    expected: str
    seen: str
    where: str  # "product" | "off_product"

    def as_record(self) -> dict[str, str]:
        return {"expected": self.expected, "seen": self.seen, "where": self.where}


@dataclass(frozen=True)
class LabelVerdict:
    status: str  # "PASS" | "MISMATCH" | "UNCHECKED"
    mismatches: tuple[LabelMismatch, ...] = ()
    verified_lines: tuple[str, ...] = ()
    reason: str = ""

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)

    def as_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mismatches": [item.as_record() for item in self.mismatches],
            "verified_lines": list(self.verified_lines),
            **({"reason": self.reason} if self.reason else {}),
        }

    def summary(self) -> str:
        return "；".join(
            f"「{item.seen}」应为「{item.expected}」" for item in self.mismatches
        )


def _wild_equal(seen: str, expected: str) -> bool:
    """True when the strings differ only where the reader wrote ?."""

    return len(seen) == len(expected) and all(
        a == b or a == "?" for a, b in zip(seen, expected, strict=True)
    )


def _is_concatenation(seen: str, lines: Sequence[str]) -> bool:
    reachable = [False] * (len(seen) + 1)
    reachable[0] = True
    for start in range(len(seen)):
        if not reachable[start]:
            continue
        for line in lines:
            if line and seen.startswith(line, start):
                reachable[start + len(line)] = True
    return reachable[-1]


def _substring_distance(text: str, pattern: str) -> int:
    """Edit distance from ``pattern`` to its best-matching substring of text."""

    previous = [0] * (len(text) + 1)
    for row, expected in enumerate(pattern, start=1):
        current = [row] + [0] * len(text)
        for column, seen in enumerate(text, start=1):
            current[column] = min(
                previous[column] + 1,
                current[column - 1] + 1,
                previous[column - 1] + (seen != expected),
            )
        previous = current
    return min(previous)


def compare(
    reference_lines: Sequence[str],
    products: Sequence[Sequence[str]],
    other_lines: Sequence[str] = (),
) -> LabelVerdict:
    """Char-exact comparison of a blind page reading against the reference.

    * A product line equal to a reference line (or a run of reference lines
      merged together) is verified.
    * A product line that is a partial read of a reference line, or that
      contains one, is neither verified nor a mismatch (cropping/occlusion).
    * Any other product line that resembles a reference line
      (SequenceMatcher ratio >= 0.5) is a typo of that line.
    * Off-product copy that quotes a reference line of 5+ characters with one
      or two changed characters (精华身体乳 for 精光身体乳) is also a typo.
    * Reference lines that are not legible at the generated size are skipped.
    """

    references = list(
        dict.fromkeys(line for line in map(normalize_line, reference_lines) if line)
    )
    originals = {normalize_line(line): str(line).strip() for line in reference_lines}
    if not references:
        return LabelVerdict("UNCHECKED", reason="reference_has_no_label_text")
    mismatches: list[LabelMismatch] = []
    verified: dict[str, None] = {}
    for instance in products:
        for raw in instance:
            seen = normalize_line(raw)
            if not seen or set(seen) == {"?"}:
                continue
            exact = next((line for line in references if seen == line), None)
            if exact is not None:
                verified[exact] = None
                continue
            if _is_concatenation(seen, references):
                for line in references:
                    if line in seen:
                        verified[line] = None
                continue
            if any(_wild_equal(seen, line) for line in references):
                continue
            if any(seen in line or line in seen for line in references):
                continue
            best = max(
                references,
                key=lambda line: difflib.SequenceMatcher(
                    None, seen, line, autojunk=False
                ).ratio(),
            )
            ratio = difflib.SequenceMatcher(None, seen, best, autojunk=False).ratio()
            if ratio >= 0.5:
                mismatches.append(
                    LabelMismatch(
                        originals.get(best, best), str(raw).strip(), "product"
                    )
                )
    for raw in other_lines:
        seen = normalize_line(raw)
        for line in references:
            if len(line) < 5 or line in seen:
                continue
            limit = 1 if len(line) < 10 else 2
            if 1 <= _substring_distance(seen, line) <= limit:
                mismatches.append(
                    LabelMismatch(
                        originals.get(line, line), str(raw).strip(), "off_product"
                    )
                )
    unique = tuple(dict.fromkeys(mismatches))
    if unique:
        return LabelVerdict(
            "MISMATCH",
            unique,
            tuple(originals.get(line, line) for line in verified),
        )
    if not verified:
        return LabelVerdict("UNCHECKED", reason="label_not_legible")
    return LabelVerdict(
        "PASS", (), tuple(originals.get(line, line) for line in verified)
    )


def parse_reading(
    payload: object,
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]] | None:
    if not isinstance(payload, Mapping):
        return None
    products = payload.get("products")
    other = payload.get("other_text_lines", [])
    if not isinstance(products, list) or not isinstance(other, list):
        return None
    parsed: list[tuple[str, ...]] = []
    for instance in products:
        lines = instance.get("label_lines") if isinstance(instance, Mapping) else None
        if not isinstance(lines, list):
            return None
        parsed.append(tuple(str(line) for line in lines if str(line).strip()))
    return tuple(parsed), tuple(str(line) for line in other if str(line).strip())


def parse_reference(payload: object) -> tuple[str, ...] | None:
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("label_lines"), list
    ):
        return None
    return tuple(
        dict.fromkeys(
            str(line).strip() for line in payload["label_lines"] if str(line).strip()
        )
    )


# --------------------------------------------------------------------------
# Image views
# --------------------------------------------------------------------------


def page_tiles(payload: bytes) -> tuple[bytes, ...]:
    """Four overlapping crops at (near) native resolution, as JPEG."""

    with Image.open(BytesIO(payload)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width, height = image.size
    tile_w = min(width, round(width / TILE_GRID * TILE_OVERLAP))
    tile_h = min(height, round(height / TILE_GRID * TILE_OVERLAP))
    tiles: list[bytes] = []
    for row in range(TILE_GRID):
        for column in range(TILE_GRID):
            left = round(column * (width - tile_w) / (TILE_GRID - 1))
            top = round(row * (height - tile_h) / (TILE_GRID - 1))
            tile = image.crop((left, top, left + tile_w, top + tile_h))
            if max(tile.size) > TILE_MAX_EDGE:
                scale = TILE_MAX_EDGE / max(tile.size)
                tile = tile.resize(
                    (round(tile.size[0] * scale), round(tile.size[1] * scale)),
                    Image.Resampling.LANCZOS,
                )
            buffer = BytesIO()
            tile.save(buffer, "JPEG", quality=95)
            tiles.append(buffer.getvalue())
    return tuple(tiles)


def _tile_sources(
    payload: bytes, *, group_key: str, role: str
) -> tuple[SourceImage, ...]:
    from .xinghe_agent import SourceImage

    return tuple(
        SourceImage(
            asset_id=f"{role}-tile-{index}",
            group_key=group_key,
            filename=f"{role}-tile-{index}.jpg",
            content_type="image/jpeg",
            sha256=hashlib.sha256(tile).hexdigest(),
            payload=tile,
            source_role=role,
        )
        for index, tile in enumerate(page_tiles(payload), start=1)
    )


# --------------------------------------------------------------------------
# Gateway calls
# --------------------------------------------------------------------------


@dataclass
class GateAccount:
    """Vision calls made by the gate for one page (reported in usage)."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    cost_micros: int = 0

    def add(self, profile: str, result: PlannerCallResult) -> None:
        self.calls.append(
            {
                "profile": profile,
                "usage": dict(result.normalized_usage),
                "latency_seconds": round(float(result.api_latency_seconds or 0), 2),
                "error_code": result.error_code,
            }
        )
        self.cost_micros += int(result.actual_cost_micros or 0)

    @property
    def requests(self) -> int:
        return len(self.calls)


def default_cache_root() -> Path:
    return Path(tempfile.gettempdir()) / "polaris-label-fidelity"


class LabelFidelityGate:
    """Reference transcription (cached per job) and blind page reads."""

    def __init__(self, gateway: XingheGateway, cache_root: Path | None = None) -> None:
        self.gateway = gateway
        self.cache_root = cache_root or default_cache_root()
        self._locks: dict[str, asyncio.Lock] = {}

    def _cache_path(self, job_id: str, digest: str) -> Path:
        safe_job = re.sub(r"[^A-Za-z0-9_.-]", "_", job_id)[:80]
        return self.cache_root / safe_job / f"label-reference-{digest[:24]}.json"

    @staticmethod
    def _read_cache(path: Path) -> tuple[str, ...] | None:
        with contextlib.suppress(OSError, ValueError):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("gate_version") == GATE_VERSION and isinstance(
                data.get("label_lines"), list
            ):
                return tuple(str(line) for line in data["label_lines"])
        return None

    async def reference_lines(
        self,
        *,
        workspace_id: str,
        job_id: str,
        idempotency_key: str,
        references: Sequence[SourceImage],
        account: GateAccount,
    ) -> tuple[str, ...] | None:
        """Label lines of the first product reference; one call per job."""

        reference = next((item for item in references if item.payload), None)
        if reference is None:
            return None
        digest = hashlib.sha256(
            f"{GATE_VERSION}:{reference.sha256}".encode()
        ).hexdigest()
        path = self._cache_path(job_id, digest)
        lock = self._locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            cached = self._read_cache(path)
            if cached is not None:
                return cached
            with contextlib.suppress(OSError):
                path.parent.mkdir(parents=True, exist_ok=True)
            handle = None
            with contextlib.suppress(OSError):
                handle = path.with_suffix(".lock").open("a")
            try:
                # Other worker processes of the same job wait for one reader.
                for _ in range(240):
                    if handle is None:
                        break
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        await asyncio.sleep(0.5)
                cached = self._read_cache(path)
                if cached is not None:
                    return cached
                lines = await self._transcribe_reference(
                    workspace_id, job_id, idempotency_key, reference, account
                )
                if lines is not None:
                    with contextlib.suppress(OSError):
                        path.write_text(
                            json.dumps(
                                {
                                    "gate_version": GATE_VERSION,
                                    "reference_sha256": reference.sha256,
                                    "label_lines": list(lines),
                                },
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )
                return lines
            finally:
                if handle is not None:
                    with contextlib.suppress(OSError):
                        fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()

    async def _transcribe_reference(
        self,
        workspace_id: str,
        job_id: str,
        idempotency_key: str,
        reference: SourceImage,
        account: GateAccount,
    ) -> tuple[str, ...] | None:
        try:
            sources = _tile_sources(
                reference.payload, group_key=job_id, role="label_reference"
            )
        except (OSError, UnidentifiedImageError, ValueError):
            return None
        result = await self._plan(
            workspace_id,
            job_id,
            f"{idempotency_key}:{GATE_VERSION}:reference:{reference.sha256[:16]}",
            sources,
            REFERENCE_PROFILE,
        )
        account.add(REFERENCE_PROFILE, result)
        if result.error_code:
            logger.warning(
                "label reference transcription failed job=%s code=%s",
                job_id,
                result.error_code,
            )
            return None
        return parse_reference(result.payload)

    async def check(
        self,
        *,
        workspace_id: str,
        job_id: str,
        idempotency_key: str,
        payload: bytes,
        reference_lines: Sequence[str],
        account: GateAccount,
    ) -> tuple[LabelVerdict, dict[str, Any] | None]:
        """Blind-read one generated image and compare it in code."""

        try:
            sources = _tile_sources(payload, group_key=job_id, role="label_candidate")
        except (OSError, UnidentifiedImageError, ValueError):
            return LabelVerdict("UNCHECKED", reason="candidate_unreadable"), None
        digest = hashlib.sha256(payload).hexdigest()
        result = await self._plan(
            workspace_id,
            job_id,
            f"{idempotency_key}:{GATE_VERSION}:read:{digest[:16]}",
            sources,
            READ_PROFILE,
        )
        account.add(READ_PROFILE, result)
        reading = None if result.error_code else parse_reading(result.payload)
        if reading is None:
            logger.warning(
                "label read failed job=%s code=%s", job_id, result.error_code
            )
            return LabelVerdict("UNCHECKED", reason="read_failed"), None
        products, other = reading
        verdict = compare(reference_lines, products, other)
        return verdict, {
            "image_sha256": digest,
            "product_label_lines": [list(lines) for lines in products],
            "other_text_lines": list(other),
        }

    async def _plan(
        self,
        workspace_id: str,
        job_id: str,
        idempotency_key: str,
        sources: tuple[SourceImage, ...],
        profile: str,
    ) -> PlannerCallResult:
        from .xinghe_agent import PlannerCallResult, PlannerRequest, normalize_usage

        try:
            return await self.gateway.plan(
                PlannerRequest(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    group_key=f"{job_id}:{profile}",
                    sources=sources,
                    page_count=1,
                    language="zh-CN",
                    product_name="product label fidelity",
                    product_information=(),
                    platform_code="LABEL_FIDELITY",
                    size="1024x1024",
                    idempotency_key=idempotency_key,
                    system_prompt=(
                        READ_SYSTEM_PROMPT
                        if profile == READ_PROFILE
                        else REFERENCE_SYSTEM_PROMPT
                    ),
                    planning_profile=profile,
                )
            )
        except Exception as exc:  # a gate failure must never fail the page
            logger.warning(
                "label gate call raised job=%s profile=%s (%s)",
                job_id,
                profile,
                type(exc).__name__,
            )
            return PlannerCallResult(
                payload=None,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                api_latency_seconds=0,
                actual_cost_micros=None,
                error_code="LABEL_GATE_CALL_FAILED",
                error_message=type(exc).__name__,
            )


def repair_instruction(
    reference_lines: Sequence[str], mismatches: Sequence[LabelMismatch]
) -> str:
    """Targeted label-repair edit prompt with a label lock."""

    fixes = "；".join(
        (
            f"商品标签上的「{item.seen}」逐字改为「{item.expected}」"
            if item.where == "product"
            else f"画面文案「{item.seen}」中的商品名逐字改为「{item.expected}」"
        )
        for item in mismatches
    )
    label = "／".join(
        str(line).strip() for line in reference_lines if str(line).strip()
    )
    return (
        "【标签定点返修】第一张图是待返修成图，其后是原商品身份参考。只修改文字，"
        f"其余像素（构图、光影、商品形状、背景、其他文案）保持不变：{fixes}。"
        f"【标签锁定】商品标签每一行必须与原商品逐字一致：{label}。"
        "不得改字、删字、增字、模糊或重新排版；字体、字号、颜色和位置沿用原图。"
    )


def residual_summary(verdict: LabelVerdict) -> str:
    return (
        f"商品标签文字与原商品不一致：{verdict.summary()}"
        "（已定点返修一次，仍未完全修正，交付较好的一版）。"
    )
