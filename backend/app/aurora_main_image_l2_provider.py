"""L2 shadow channel for injecting the bundled Skill references at generation.

The v2 Harness already compiles the page contracts, but the website image
provider previously sent only those compiled prompts.  The original Skill
expects an Agent to read its references before planning, compiling, judging,
and repairing.  This channel carries the original generation-stage reference
text into the actual image request without changing the Harness, source files,
identity references, or the default provider path.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from .aurora_l2_references import (
    L2_GENERATION_REFERENCE_FILES,
    L2_REPAIR_REFERENCE,
    append_l2_reference_sections,
    load_l2_reference_sections,
)
from .aurora_main_image_l1_provider import AuroraMainImageL1Provider
from .config import default_aurora_v20_skill_root
from .provider import ProviderRequest
from .storage import ImageStorage
from .xinghe_agent import XingheGateway


class AuroraMainImageL2Provider(AuroraMainImageL1Provider):
    """L1 audit channel plus original Skill reference injection for generation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        storage: ImageStorage,
        *,
        harness: Any | None = None,
        work_root: Path | None = None,
        execution_mode: str = "sequential_v017",
        skill_root: Path | None = None,
    ) -> None:
        super().__init__(
            session_factory,
            gateway,
            storage,
            harness=harness,
            work_root=work_root,
            execution_mode=execution_mode,
        )
        self._skill_root = (skill_root or default_aurora_v20_skill_root()).resolve()
        self._l2_reference_bundle: tuple[tuple[str, str], ...] | None = None

    def _augment_generation_request(
        self,
        request: ProviderRequest,
        generation_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append only the original Skill's staged reference text.

        The method is idempotent so a retained candidate from a prior attempt
        is never given duplicate reference text.  All Harness-owned fields,
        especially the generation token and image references, are preserved.
        """

        result = dict(generation_request)
        if result.get("aurora_l2_reference_bundle"):
            return result
        prompt = str(result.get("prompt") or "").rstrip()
        sections = list(self._generation_reference_bundle())
        if result.get("generation_origin") == "AUTOMATIC_REPAIR":
            sections.append(self._repair_reference_section())
        result["prompt"] = append_l2_reference_sections(
            prompt,
            tuple(sections),
            stage=(
                "repair"
                if result.get("generation_origin") == "AUTOMATIC_REPAIR"
                else "generation"
            ),
        )
        result["aurora_l2_reference_bundle"] = [name for name, _ in sections]
        result["aurora_l2_reference_stage"] = (
            "repair"
            if result.get("generation_origin") == "AUTOMATIC_REPAIR"
            else "generation"
        )
        return result

    def _generation_reference_bundle(self) -> tuple[tuple[str, str], ...]:
        if self._l2_reference_bundle is None:
            self._l2_reference_bundle = load_l2_reference_sections(
                self._skill_root,
                L2_GENERATION_REFERENCE_FILES,
            )
        return self._l2_reference_bundle

    def _repair_reference_section(self) -> tuple[str, str]:
        path = self._skill_root / L2_REPAIR_REFERENCE
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Aurora L2 repair reference is unreadable at {path}: {exc}"
            ) from exc
        # The shipped reference uses a prose lead-in rather than a Markdown
        # heading. Preserve the original text verbatim from that paragraph.
        lead_in = "Ordinary repair edits"
        start = content.find(lead_in)
        if start < 0:
            raise RuntimeError(
                f"Aurora L2 repair reference section is missing at {path}"
            )
        return (L2_REPAIR_REFERENCE.as_posix(), content[start:])
