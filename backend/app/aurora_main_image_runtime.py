"""Narrow subprocess boundary for the bundled Aurora six-image Harness.

The web application never imports or invokes the Skill's runtime helpers directly.
Every state transition goes through ``scripts/harness.py`` with an argv allowlist,
no shell, a fixed interpreter, and paths constrained to a per-job workspace.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import default_skill_root

AURORA_MAIN_IMAGE_SKILL_ID = "aurora-domestic-ecommerce-main-image"
AURORA_MAIN_IMAGE_VERSION = "0.1.17"


class AuroraHarnessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_COMMAND_ARGUMENTS: dict[str, frozenset[str]] = {
    "start": frozenset({"input", "session"}),
    "lock-identity": frozenset({"session", "identity"}),
    "compile": frozenset({"session", "plan"}),
    "compile-v013": frozenset(
        {"session", "input", "identity", "source-manifest", "output"}
    ),
    "replan": frozenset({"session", "plan", "reason"}),
    "restart-campaign": frozenset({"session", "reason"}),
    "authorize": frozenset({"session", "approval-text"}),
    "generate-next": frozenset({"session", "out"}),
    "record-generation": frozenset({"session", "token", "image"}),
    "audit-current": frozenset({"session", "judgment"}),
    "calibrate-search-baseline": frozenset({"session", "observation"}),
    "audit-set-role-distinction": frozenset({"session", "observation"}),
    "prepare-repair": frozenset({"session", "repair-plan"}),
    "apply-user-adjustment": frozenset({"session", "adjustment"}),
    "calibrate-style": frozenset({"session", "observation"}),
    "finalize": frozenset({"session", "output", "approval-text"}),
    "inspect": frozenset({"session"}),
}


@dataclass(frozen=True)
class AuroraHarnessRunner:
    skill_root: Path = default_skill_root(AURORA_MAIN_IMAGE_SKILL_ID)
    timeout_seconds: float = 45

    def run(
        self,
        command: str,
        workspace: Path,
        arguments: Mapping[str, str | Path],
    ) -> dict[str, Any]:
        allowed = _COMMAND_ARGUMENTS.get(command)
        if allowed is None:
            raise AuroraHarnessError("HARNESS_COMMAND_NOT_ALLOWED", command)
        unexpected = set(arguments) - allowed
        if unexpected:
            raise AuroraHarnessError(
                "HARNESS_ARGUMENT_NOT_ALLOWED",
                f"Unsupported arguments for {command}: {sorted(unexpected)}",
            )
        root = workspace.resolve()
        root.mkdir(parents=True, exist_ok=True)
        argv: list[str] = [sys.executable, str(self.harness_path), command]
        for name, raw_value in arguments.items():
            value = str(raw_value)
            if name not in {"reason", "approval-text", "token"}:
                value = str(self._workspace_path(root, Path(value)))
            argv.extend((f"--{name}", value))
        try:
            completed = subprocess.run(
                argv,
                cwd=self.skill_root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AuroraHarnessError(
                "HARNESS_TIMEOUT", "Aurora Harness timed out"
            ) from exc
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AuroraHarnessError(
                "HARNESS_INVALID_OUTPUT", "Aurora Harness did not return JSON"
            ) from exc
        if completed.returncode != 0 or result.get("status") == "BLOCKED":
            message = str(
                result.get("error") or "Aurora Harness blocked the transition"
            )
            raise AuroraHarnessError("HARNESS_BLOCKED", message)
        return result

    @property
    def harness_path(self) -> Path:
        path = (self.skill_root / "scripts" / "harness.py").resolve()
        if not path.is_file() or self.skill_root.resolve() not in path.parents:
            raise AuroraHarnessError(
                "HARNESS_MISSING", "Bundled Aurora Harness is missing"
            )
        return path

    @staticmethod
    def _workspace_path(root: Path, value: Path) -> Path:
        candidate = value if value.is_absolute() else root / value
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            raise AuroraHarnessError(
                "HARNESS_PATH_OUTSIDE_WORKSPACE",
                "Harness file arguments must remain inside the job workspace",
            )
        return resolved


def write_contract(path: Path, value: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
