"""Immutable harness boundary for the Aurora domestic main-image Skill."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKILL_NAME = "aurora-domestic-ecommerce-main-image"
SKILL_VERSION = "0.1.17"
LOCK_SCHEMA = "polaris-frozen-skill-lock-v1"
CONTENT_HASH_ALGORITHM = "sha256-ordered-path-nul-file-sha256-lf-v1"
PUBLIC_COMMANDS = frozenset(
    {
        "start",
        "lock-identity",
        "compile",
        "compile-v013",
        "replan",
        "restart-campaign",
        "authorize",
        "generate-next",
        "record-generation",
        "audit-current",
        "calibrate-search-baseline",
        "audit-set-role-distinction",
        "prepare-repair",
        "apply-user-adjustment",
        "calibrate-style",
        "finalize",
        "inspect",
    }
)


class DomesticMainImageRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


@dataclass(frozen=True)
class FrozenSkillPackage:
    root: Path
    lock_path: Path
    skill_digest: str
    source_zip_sha256: str
    files: tuple[dict[str, Any], ...]

    @classmethod
    def load(cls, root: Path, lock_path: Path) -> FrozenSkillPackage:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DomesticMainImageRuntimeError(
                "SKILL_LOCK_INVALID", "Domestic main-image Skill lock is unreadable."
            ) from exc
        if (
            payload.get("schema_version") != LOCK_SCHEMA
            or payload.get("skill_name") != SKILL_NAME
            or payload.get("skill_version") != SKILL_VERSION
            or payload.get("content_hash_algorithm") != CONTENT_HASH_ALGORITHM
            or payload.get("harness_entrypoint") != "scripts/harness.py"
            or not isinstance(payload.get("files"), list)
        ):
            raise DomesticMainImageRuntimeError(
                "SKILL_LOCK_INVALID", "Domestic main-image Skill lock is incomplete."
            )
        package = cls(
            root=root.resolve(),
            lock_path=lock_path.resolve(),
            skill_digest=str(payload["skill_digest"]),
            source_zip_sha256=str(payload["source_zip_sha256"]),
            files=tuple(payload["files"]),
        )
        package.verify()
        return package

    @property
    def harness_path(self) -> Path:
        return self.root / "scripts" / "harness.py"

    def inventory_snapshot(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.files]

    def verify(self) -> None:
        expected = {str(item["path"]): item for item in self.files}
        actual_paths = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        }
        if actual_paths != set(expected):
            raise DomesticMainImageRuntimeError(
                "SKILL_CONTENT_MISMATCH", "Frozen Skill file inventory drifted."
            )
        canonical: list[str] = []
        for relative in sorted(expected):
            path = self.root / Path(relative)
            digest = _sha256_bytes(path.read_bytes())
            if digest != expected[relative].get("sha256"):
                raise DomesticMainImageRuntimeError(
                    "SKILL_CONTENT_MISMATCH",
                    f"Frozen Skill file changed: {relative}.",
                )
            canonical.append(f"{relative}\0{digest}\n")
        if _sha256_bytes("".join(canonical).encode("utf-8")) != self.skill_digest:
            raise DomesticMainImageRuntimeError(
                "SKILL_CONTENT_MISMATCH", "Frozen Skill digest drifted."
            )


@dataclass(frozen=True)
class HarnessInvocation:
    command: str
    argv: tuple[str, ...]
    command_input: dict[str, Any]
    exit_code: int
    stdout: str
    stderr: str
    result: dict[str, Any] | None
    session: dict[str, Any] | None
    artifacts: dict[str, Any]


class HarnessAdapter:
    """Runs only ``python scripts/harness.py`` against an isolated session copy."""

    def __init__(
        self,
        package: FrozenSkillPackage,
        *,
        python_executable: Path | None = None,
        timeout_seconds: int = 180,
    ) -> None:
        self.package = package
        self.python_executable = (python_executable or Path(sys.executable)).resolve()
        self.timeout_seconds = timeout_seconds

    def probe(self) -> tuple[bool, str | None]:
        self.package.verify()
        env = os.environ.copy()
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        try:
            completed = subprocess.run(
                [str(self.python_executable), str(self.package.harness_path), "--help"],
                cwd=self.package.root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, type(exc).__name__
        if completed.returncode != 0:
            return False, completed.stderr.strip() or "HARNESS_PROBE_FAILED"
        return True, None

    def run(
        self,
        command: str,
        *,
        session: dict[str, Any] | None,
        json_arguments: dict[str, object] | None = None,
        text_arguments: dict[str, str] | None = None,
        output_argument: str | None = None,
    ) -> HarnessInvocation:
        if command not in PUBLIC_COMMANDS:
            raise DomesticMainImageRuntimeError(
                "HARNESS_COMMAND_FORBIDDEN", f"Unsupported harness command: {command}."
            )
        self.package.verify()
        json_arguments = json_arguments or {}
        text_arguments = text_arguments or {}
        with tempfile.TemporaryDirectory(prefix="polaris-main-image-") as temp_value:
            temp = Path(temp_value)
            session_path = temp / "session.json"
            if session is not None:
                session_path.write_text(
                    json.dumps(session, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            argv = [
                str(self.python_executable),
                str(self.package.harness_path),
                command,
            ]
            if command == "start" or session is not None:
                argv.extend(["--session", str(session_path)])
            command_input: dict[str, Any] = {}
            for name, value in json_arguments.items():
                argument_path = temp / f"{name.replace('-', '_')}.json"
                argument_path.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                argv.extend([f"--{name}", str(argument_path)])
                command_input[name] = value
            for name, value in text_arguments.items():
                argv.extend([f"--{name}", value])
                command_input[name] = value
            output_path: Path | None = None
            if output_argument is not None:
                output_path = temp / f"{output_argument.replace('-', '_')}.json"
                argv.extend([f"--{output_argument}", str(output_path)])
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            try:
                completed = subprocess.run(
                    argv,
                    cwd=self.package.root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DomesticMainImageRuntimeError(
                    "HARNESS_UNAVAILABLE", "Domestic main-image harness could not run."
                ) from exc
            result = self._read_stdout(completed.stdout)
            next_session = None
            artifacts: dict[str, Any] = {}
            if completed.returncode == 0:
                try:
                    next_session = json.loads(session_path.read_text(encoding="utf-8"))
                    if output_path is not None and output_path.exists():
                        artifacts[output_argument or "output"] = json.loads(
                            output_path.read_text(encoding="utf-8")
                        )
                except (OSError, json.JSONDecodeError) as exc:
                    raise DomesticMainImageRuntimeError(
                        "HARNESS_OUTPUT_INVALID", "Harness returned invalid UTF-8 JSON."
                    ) from exc
            return HarnessInvocation(
                command=command,
                argv=tuple(argv),
                command_input=command_input,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                result=result,
                session=next_session,
                artifacts=artifacts,
            )

    @staticmethod
    def _read_stdout(stdout: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


def default_frozen_package() -> FrozenSkillPackage:
    backend_root = Path(__file__).resolve().parents[1]
    return FrozenSkillPackage.load(
        backend_root / "skill_sources" / SKILL_NAME,
        Path(__file__).resolve().with_name("skill_manifests")
        / "domestic_main_image"
        / f"{SKILL_NAME}.lock.json",
    )
