"""Runtime adapter for the frozen Aurora domestic detail-page Skill v0.7.0.

The bundled Skill is an immutable executable dependency.  This module never
imports ``scripts/runtime`` and never reconstructs its state machine.  Every
transition is delegated to ``python scripts/harness.py ...`` and the resulting
session JSON is returned to the caller for durable database persistence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import default_skill_root
from .skill_runtime import SkillManifestRegistry

AURORA_DETAIL_SKILL_ID = "aurora-domestic-ecommerce-detail-page"
AURORA_DETAIL_VERSION = "0.7.0"
HARNESS_TIMEOUT_SECONDS = 120


class AuroraDetailRuntimeError(RuntimeError):
    """Fail-closed adapter error with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HarnessResult:
    summary: dict[str, Any]
    session: dict[str, Any]


@dataclass(frozen=True)
class GenerationProviderCapabilities:
    ordered_references: bool
    primary_edit_image: bool
    fixed_model_version: bool
    idempotency: bool
    request_recovery: bool


@dataclass(frozen=True)
class GenerationEnvelope:
    token: str
    module_id: str
    mode: str
    prompt: str
    prompt_sha256: str
    reference_images: tuple[str, ...]
    reference_sha256: tuple[str, ...]
    edit_target: str | None
    edit_target_sha256: str | None
    model: str
    model_version: str
    endpoint: str
    parameters: Mapping[str, Any]
    idempotency_key: str
    context_contract: Mapping[str, Any]


class AuroraDetailHarnessAdapter:
    """Execute the frozen harness in a stable, restart-safe working directory."""

    def __init__(
        self,
        runtime_root: Path,
        *,
        skill_root: Path | None = None,
        python_executable: str | None = None,
        registry: SkillManifestRegistry | None = None,
    ) -> None:
        self.runtime_root = runtime_root.resolve()
        self.skill_root = (
            skill_root or default_skill_root(AURORA_DETAIL_SKILL_ID)
        ).resolve()
        self.python_executable = python_executable or sys.executable
        self.registry = registry or SkillManifestRegistry.bundled()

    def start(self, session_key: str, raw_input: Mapping[str, Any]) -> HarnessResult:
        workdir = self._workdir(session_key)
        self._verify_skill()
        input_path = workdir / "input.json"
        session_path = workdir / "session.json"
        self._write_json(input_path, raw_input)
        summary = self._run("start", "--input", input_path, "--session", session_path)
        return HarnessResult(summary=summary, session=self._read_json(session_path))

    def inspect(self, session_key: str, session: Mapping[str, Any]) -> HarnessResult:
        return self._session_command(session_key, session, "inspect")

    def resolve_conflicts(
        self,
        session_key: str,
        session: Mapping[str, Any],
        resolution: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key,
            session,
            "resolve-conflicts",
            "resolution",
            resolution,
        )

    def lock_identity(
        self,
        session_key: str,
        session: Mapping[str, Any],
        identity: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key, session, "lock-identity", "identity", identity
        )

    def compile_plan(
        self,
        session_key: str,
        session: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key, session, "compile-plan", "plan", plan
        )

    def authorize(
        self,
        session_key: str,
        session: Mapping[str, Any],
        *,
        approval_text: str,
        approved_module_count: int,
        approved_aspect_ratio: str,
    ) -> HarnessResult:
        return self._session_command(
            session_key,
            session,
            "authorize",
            "--approval-text",
            approval_text,
            "--approved-module-count",
            str(approved_module_count),
            "--approved-aspect-ratio",
            approved_aspect_ratio,
        )

    def generate_next(
        self, session_key: str, session: Mapping[str, Any]
    ) -> tuple[HarnessResult, dict[str, Any]]:
        workdir, session_path = self._rehydrate(session_key, session)
        request_path = workdir / "generation-request.json"
        summary = self._run(
            "generate-next",
            "--session",
            session_path,
            "--out",
            request_path,
        )
        result = HarnessResult(summary=summary, session=self._read_json(session_path))
        return result, self._read_json(request_path)

    def record_generation(
        self,
        session_key: str,
        session: Mapping[str, Any],
        *,
        token: str,
        image_path: Path,
    ) -> HarnessResult:
        return self._session_command(
            session_key,
            session,
            "record-generation",
            "--token",
            token,
            "--image",
            str(image_path.resolve()),
        )

    def audit_current(
        self,
        session_key: str,
        session: Mapping[str, Any],
        judgment: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key, session, "audit-current", "judgment", judgment
        )

    def prepare_repair(
        self,
        session_key: str,
        session: Mapping[str, Any],
        repair_plan: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key,
            session,
            "prepare-repair",
            "repair-plan",
            repair_plan,
        )

    def apply_user_adjustment(
        self,
        session_key: str,
        session: Mapping[str, Any],
        adjustment: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key,
            session,
            "apply-user-adjustment",
            "adjustment",
            adjustment,
        )

    def assemble(
        self,
        session_key: str,
        session: Mapping[str, Any],
        output_path: Path,
    ) -> HarnessResult:
        return self._session_command(
            session_key,
            session,
            "assemble",
            "--output",
            str(output_path.resolve()),
        )

    def audit_long_page(
        self,
        session_key: str,
        session: Mapping[str, Any],
        judgment: Mapping[str, Any],
    ) -> HarnessResult:
        return self._document_command(
            session_key,
            session,
            "audit-long-page",
            "judgment",
            judgment,
        )

    def finalize(
        self,
        session_key: str,
        session: Mapping[str, Any],
        *,
        output_path: Path,
        approval_text: str,
    ) -> HarnessResult:
        return self._session_command(
            session_key,
            session,
            "finalize",
            "--output",
            str(output_path.resolve()),
            "--approval-text",
            approval_text,
        )

    def _document_command(
        self,
        session_key: str,
        session: Mapping[str, Any],
        command: str,
        option_name: str,
        document: Mapping[str, Any],
    ) -> HarnessResult:
        workdir, session_path = self._rehydrate(session_key, session)
        document_path = workdir / f"{option_name}.json"
        self._write_json(document_path, document)
        summary = self._run(
            command,
            "--session",
            session_path,
            f"--{option_name}",
            document_path,
        )
        return HarnessResult(summary=summary, session=self._read_json(session_path))

    def _session_command(
        self,
        session_key: str,
        session: Mapping[str, Any],
        command: str,
        *arguments: str | Path,
    ) -> HarnessResult:
        _, session_path = self._rehydrate(session_key, session)
        summary = self._run(command, "--session", session_path, *arguments)
        return HarnessResult(summary=summary, session=self._read_json(session_path))

    def _rehydrate(
        self, session_key: str, session: Mapping[str, Any]
    ) -> tuple[Path, Path]:
        self._verify_skill()
        workdir = self._workdir(session_key)
        session_path = workdir / "session.json"
        self._write_json(session_path, session)
        return workdir, session_path

    def _verify_skill(self) -> None:
        self.registry.verify_source(AURORA_DETAIL_SKILL_ID, self.skill_root)
        try:
            version = (self.skill_root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AuroraDetailRuntimeError(
                "AURORA_SKILL_VERSION_MISSING", "Aurora Skill VERSION is missing."
            ) from exc
        if version != AURORA_DETAIL_VERSION:
            raise AuroraDetailRuntimeError(
                "AURORA_SKILL_VERSION_MISMATCH",
                f"Expected Aurora Skill {AURORA_DETAIL_VERSION}, got {version}.",
            )

    def _workdir(self, session_key: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", session_key):
            raise AuroraDetailRuntimeError(
                "AURORA_SESSION_KEY_INVALID", "Session key is not filesystem-safe."
            )
        path = (self.runtime_root / session_key).resolve()
        if self.runtime_root != path.parent:
            raise AuroraDetailRuntimeError(
                "AURORA_SESSION_PATH_INVALID", "Session path escaped runtime root."
            )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _run(self, command: str, *arguments: str | Path) -> dict[str, Any]:
        harness = self.skill_root / "scripts" / "harness.py"
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            completed = subprocess.run(
                [
                    self.python_executable,
                    str(harness),
                    command,
                    *(str(item) for item in arguments),
                ],
                cwd=self.skill_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=HARNESS_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuroraDetailRuntimeError(
                "AURORA_HARNESS_UNAVAILABLE",
                f"Aurora harness could not run ({type(exc).__name__}).",
            ) from exc
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            try:
                decoded = json.loads(message)
                message = str(decoded.get("error") or message)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise AuroraDetailRuntimeError(
                "AURORA_HARNESS_REJECTED", message or "Aurora harness rejected command."
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AuroraDetailRuntimeError(
                "AURORA_HARNESS_RESPONSE_INVALID",
                "Aurora harness returned invalid JSON.",
            ) from exc
        if not isinstance(payload, dict):
            raise AuroraDetailRuntimeError(
                "AURORA_HARNESS_RESPONSE_INVALID",
                "Aurora harness response must be an object.",
            )
        return payload

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".new")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuroraDetailRuntimeError(
                "AURORA_SESSION_INVALID", "Aurora session JSON is unavailable."
            ) from exc
        if not isinstance(payload, dict):
            raise AuroraDetailRuntimeError(
                "AURORA_SESSION_INVALID", "Aurora session must be an object."
            )
        return payload


def compile_generation_envelope(
    request: Mapping[str, Any],
    session: Mapping[str, Any],
    *,
    capabilities: GenerationProviderCapabilities,
    model: str,
    model_version: str,
    endpoint: str,
    parameters: Mapping[str, Any],
    idempotency_key: str,
) -> GenerationEnvelope:
    """Validate the harness request before any billable provider boundary."""

    required_capabilities = (
        capabilities.ordered_references,
        capabilities.fixed_model_version,
        capabilities.idempotency,
        capabilities.request_recovery,
    )
    if not all(required_capabilities):
        raise AuroraDetailRuntimeError(
            "AURORA_PROVIDER_CAPABILITY_MISMATCH",
            "Provider lacks ordered references, fixed version, "
            "idempotency, or recovery.",
        )
    prompt = _required_string(request, "prompt")
    token = _required_string(request, "token")
    module_id = _required_string(request, "module_id")
    mode = _required_string(request, "mode")
    context = _required_mapping(request, "context_contract")
    references_value = request.get("reference_images")
    if (
        not isinstance(references_value, list)
        or not references_value
        or not all(isinstance(item, str) and item for item in references_value)
    ):
        raise AuroraDetailRuntimeError(
            "AURORA_REFERENCES_INVALID", "Harness references must be ordered paths."
        )
    references = tuple(references_value)
    edit_target_value = request.get("edit_target")
    edit_target = edit_target_value if isinstance(edit_target_value, str) else None
    if edit_target is not None and not capabilities.primary_edit_image:
        raise AuroraDetailRuntimeError(
            "AURORA_PROVIDER_EDIT_TARGET_UNSUPPORTED",
            "Provider cannot preserve the required edit target as the repair canvas.",
        )
    identity = _required_mapping(session, "identity")
    plan = _required_mapping(session, "plan")
    if (
        context.get("canonical_product") != identity.get("canonical_name")
        or context.get("module_id") != module_id
        or context.get("identity_fingerprint") != _harness_fingerprint(identity)
        or context.get("approved_plan_fingerprint") != _harness_fingerprint(plan)
        or context.get("prompt_fingerprint") != _harness_fingerprint(prompt)
        or context.get("reference_count") != len(references)
        or context.get("compiled_prompt_locked") is not True
    ):
        raise AuroraDetailRuntimeError(
            "AURORA_CONTEXT_CONTRACT_STALE",
            "Generation context does not match the durable approved session.",
        )
    current_index = session.get("current_index")
    modules = session.get("modules")
    if (
        not isinstance(current_index, int)
        or not isinstance(modules, list)
        or current_index < 0
        or current_index >= len(modules)
        or not isinstance(modules[current_index], Mapping)
        or modules[current_index].get("id") != module_id
    ):
        raise AuroraDetailRuntimeError(
            "AURORA_CURRENT_MODULE_STALE",
            "Generation request does not target the durable current module.",
        )
    return GenerationEnvelope(
        token=token,
        module_id=module_id,
        mode=mode,
        prompt=prompt,
        prompt_sha256=_file_or_text_sha256(prompt),
        reference_images=references,
        reference_sha256=tuple(_path_sha256(Path(item)) for item in references),
        edit_target=edit_target,
        edit_target_sha256=(
            _path_sha256(Path(edit_target)) if edit_target is not None else None
        ),
        model=_required_nonempty(model, "model"),
        model_version=_required_nonempty(model_version, "model_version"),
        endpoint=_required_nonempty(endpoint, "endpoint"),
        parameters=dict(parameters),
        idempotency_key=_required_nonempty(idempotency_key, "idempotency_key"),
        context_contract=dict(context),
    )


def assert_provider_receipt(
    envelope: GenerationEnvelope,
    *,
    prompt_sha256: str,
    ordered_reference_sha256: Sequence[str],
    edit_target_sha256: str | None,
    model: str,
    model_version: str,
    endpoint: str,
    parameters: Mapping[str, Any],
) -> None:
    """Fail if the actual provider call drifted from the harness contract."""

    if (
        prompt_sha256 != envelope.prompt_sha256
        or tuple(ordered_reference_sha256) != envelope.reference_sha256
        or edit_target_sha256 != envelope.edit_target_sha256
        or model != envelope.model
        or model_version != envelope.model_version
        or endpoint != envelope.endpoint
        or dict(parameters) != dict(envelope.parameters)
    ):
        raise AuroraDetailRuntimeError(
            "AURORA_PROVIDER_RECEIPT_MISMATCH",
            "Provider receipt differs from the locked generation envelope.",
        )


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    candidate = value.get(key)
    if not isinstance(candidate, Mapping):
        raise AuroraDetailRuntimeError(
            "AURORA_CONTRACT_INVALID", f"{key} must be an object."
        )
    return candidate


def _required_string(value: Mapping[str, Any], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate:
        raise AuroraDetailRuntimeError(
            "AURORA_CONTRACT_INVALID", f"{key} must be a non-empty string."
        )
    return candidate


def _required_nonempty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AuroraDetailRuntimeError(
            "AURORA_PROVIDER_CONFIGURATION_INVALID", f"{field} is required."
        )
    return normalized


def _harness_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_or_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_sha256(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AuroraDetailRuntimeError(
            "AURORA_REFERENCE_UNAVAILABLE",
            f"Generation reference is unavailable: {path.name}.",
        ) from exc
    return hashlib.sha256(payload).hexdigest()
