"""Original Aurora Skill reference loading for the L2 shadow channel."""

from __future__ import annotations

from pathlib import Path

L2_PLANNING_REFERENCE_FILES = (
    Path("references") / "core-policy.md",
    Path("references") / "six-page-strategy.md",
)
L2_GENERATION_REFERENCE_FILES = (
    Path("references") / "visual-strategy.md",
    Path("references") / "commercial-performance.md",
)
L2_REPAIR_REFERENCE = Path("references") / "visual-audit.md"
L2_REFERENCE_MARKER = "[AURORA L2 ORIGINAL SKILL REFERENCES]"


def load_l2_reference_sections(
    skill_root: Path,
    relative_files: tuple[Path, ...],
) -> tuple[tuple[str, str], ...]:
    """Read the requested original Skill references verbatim and fail loud."""

    loaded: list[tuple[str, str]] = []
    for relative in relative_files:
        path = skill_root / relative
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Aurora L2 reference is unreadable at {path}: {exc}"
            ) from exc
        if not content:
            raise RuntimeError(f"Aurora L2 reference is empty at {path}")
        loaded.append((relative.as_posix(), content))
    return tuple(loaded)


def append_l2_reference_sections(
    prompt: str,
    sections: tuple[tuple[str, str], ...],
    *,
    stage: str,
) -> str:
    """Append a staged bundle without changing any existing prompt text."""

    rendered = [str(prompt).rstrip(), "", f"{L2_REFERENCE_MARKER} ({stage})"]
    for name, content in sections:
        rendered.extend((f"--- {name} ---", content, ""))
    return "\n".join(rendered).rstrip()
