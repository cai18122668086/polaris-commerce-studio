"""Zero-cost orchestration for the Aurora domestic main-image Skill."""

from __future__ import annotations

import hashlib
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .domestic_main_image_models import (
    DomesticMainImageCommandRecord,
    DomesticMainImagePageRecord,
    DomesticMainImageSourceRecord,
    DomesticMainImageTaskRecord,
)
from .domestic_main_image_runtime import (
    SKILL_NAME,
    SKILL_VERSION,
    DomesticMainImageRuntimeError,
    FrozenSkillPackage,
    HarnessAdapter,
    HarnessInvocation,
    canonical_json_sha256,
)
from .errors import ApiError
from .models import AssetRecord
from .services import new_id

TECHNICAL_RUNNING = "RUNNING"
TECHNICAL_FAILED = "SYSTEM_FAILED"


def resolve_startup_commit(configured: str, repository_root: Path) -> str:
    value = configured.strip().lower()
    if len(value) == 40 and all(character in "0123456789abcdef" for character in value):
        return value
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DomesticMainImageRuntimeError(
            "STARTUP_COMMIT_UNKNOWN",
            "The startup Git commit is required for domestic main-image tasks.",
        ) from exc
    commit = completed.stdout.strip().lower()
    if len(commit) != 40:
        raise DomesticMainImageRuntimeError(
            "STARTUP_COMMIT_UNKNOWN", "The startup Git commit is invalid."
        )
    return commit


async def materialize_asset(
    *,
    storage: Any,
    asset: AssetRecord,
    cache_root: Path,
) -> Path:
    payload = await storage.read_bytes(asset.object_key)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != asset.sha256:
        raise DomesticMainImageRuntimeError(
            "ASSET_INTEGRITY_MISMATCH", f"Asset integrity failed: {asset.id}."
        )
    suffix_by_type = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    suffix = suffix_by_type.get(asset.content_type)
    if suffix is None:
        raise DomesticMainImageRuntimeError(
            "ASSET_TYPE_UNSUPPORTED", f"Unsupported source image: {asset.id}."
        )
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = (cache_root / f"{digest}{suffix}").resolve()
    if not destination.is_relative_to(cache_root.resolve()):
        raise DomesticMainImageRuntimeError(
            "ASSET_PATH_UNSAFE", "Resolved asset path escaped its cache root."
        )
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise DomesticMainImageRuntimeError(
                "ASSET_CACHE_CORRUPT", f"Cached asset is corrupt: {asset.id}."
            )
    else:
        destination.write_bytes(payload)
    return destination


class DomesticMainImageOrchestrator:
    def __init__(
        self,
        package: FrozenSkillPackage,
        harness: HarnessAdapter,
        *,
        startup_git_commit: str,
        image_model: str | None,
        image_model_version: str | None,
    ) -> None:
        self.package = package
        self.harness = harness
        self.startup_git_commit = startup_git_commit
        self.image_model = image_model or None
        self.image_model_version = image_model_version or None

    def create_task(
        self,
        session: Session,
        *,
        workspace_id: str,
        user_id: str,
        raw_input: dict[str, Any],
        sources: list[dict[str, Any]],
        idempotency_key: str,
        request_sha256: str,
    ) -> DomesticMainImageTaskRecord:
        invocation = self.harness.run(
            "start", session=None, json_arguments={"input": raw_input}
        )
        self._require_success(invocation)
        assert invocation.session is not None
        task = DomesticMainImageTaskRecord(
            id=new_id("mainimg"),
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            create_idempotency_key=idempotency_key,
            create_request_sha256=request_sha256,
            technical_status=TECHNICAL_RUNNING,
            skill_state=str(invocation.session["state"]),
            revision=0,
            session_payload=invocation.session,
            raw_input=raw_input,
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            skill_digest=self.package.skill_digest,
            skill_file_inventory=self.package.inventory_snapshot(),
            source_zip_sha256=self.package.source_zip_sha256,
            startup_git_commit=self.startup_git_commit,
            image_model=self.image_model,
            image_model_version=self.image_model_version,
            provider_capability_status="UNVERIFIED",
        )
        session.add(task)
        for source in sources:
            session.add(
                DomesticMainImageSourceRecord(
                    id=new_id("mainsrc"),
                    task_id=task.id,
                    asset_id=source["asset_id"],
                    evidence_id=source["evidence_id"],
                    ordinal=source["ordinal"],
                    source_role=source["role"],
                    runtime_path=source["path"],
                    asset_sha256=source["sha256"],
                )
            )
        for page_index in range(6):
            session.add(
                DomesticMainImagePageRecord(
                    id=new_id("mainpage"),
                    task_id=task.id,
                    page_index=page_index,
                    display_status="WAITING",
                    residual_issues=[],
                )
            )
        session.add(self._command_record(task, invocation, sequence=1, committed=0))
        session.commit()
        session.refresh(task)
        return task

    def lock_identity_and_compile(
        self,
        session: Session,
        *,
        task: DomesticMainImageTaskRecord,
        expected_revision: int,
        identity_contract: dict[str, Any],
    ) -> DomesticMainImageTaskRecord:
        identity = self._bind_identity_paths(session, task, identity_contract)
        task = self._advance(
            session,
            task=task,
            expected_revision=expected_revision,
            command="lock-identity",
            json_arguments={"identity": identity},
            task_values={"identity_contract": identity},
        )
        task = self._advance(
            session,
            task=task,
            expected_revision=task.revision,
            command="compile-v013",
            output_argument="output",
            task_values={},
        )
        task.plan_payload = deepcopy(task.session_payload.get("plan"))
        session.commit()
        session.refresh(task)
        return task

    def authorize_and_prepare_first_generation(
        self,
        session: Session,
        *,
        task: DomesticMainImageTaskRecord,
        expected_revision: int,
        approval_text: str,
    ) -> DomesticMainImageTaskRecord:
        task = self._advance(
            session,
            task=task,
            expected_revision=expected_revision,
            command="authorize",
            text_arguments={"approval-text": approval_text},
            task_values={},
        )
        task = self._advance(
            session,
            task=task,
            expected_revision=task.revision,
            command="generate-next",
            output_argument="out",
            task_values={},
        )
        request = self._validate_generation_request(task)
        task.generation_request = request
        session.commit()
        session.refresh(task)
        return task

    def _advance(
        self,
        session: Session,
        *,
        task: DomesticMainImageTaskRecord,
        expected_revision: int,
        command: str,
        task_values: dict[str, Any],
        json_arguments: dict[str, object] | None = None,
        text_arguments: dict[str, str] | None = None,
        output_argument: str | None = None,
    ) -> DomesticMainImageTaskRecord:
        if task.revision != expected_revision:
            raise ApiError(
                409, "STALE_SESSION_REVISION", "任务已由另一个请求推进，请刷新后重试。"
            )
        before = deepcopy(task.session_payload)
        invocation = self.harness.run(
            command,
            session=before,
            json_arguments=json_arguments,
            text_arguments=text_arguments,
            output_argument=output_argument,
        )
        sequence = self._next_sequence(session, task.id)
        if invocation.exit_code != 0 or invocation.session is None:
            task.technical_status = TECHNICAL_FAILED
            task.last_error_code = "HARNESS_COMMAND_FAILED"
            task.last_error_message = self._failure_message(invocation)
            session.add(
                self._command_record(
                    task,
                    invocation,
                    sequence=sequence,
                    committed=None,
                    before=before,
                )
            )
            session.commit()
            raise DomesticMainImageRuntimeError(
                "HARNESS_COMMAND_FAILED", task.last_error_message
            )
        next_revision = expected_revision + 1
        values = {
            "session_payload": invocation.session,
            "skill_state": str(invocation.session["state"]),
            "revision": next_revision,
            "technical_status": TECHNICAL_RUNNING,
            "last_error_code": None,
            "last_error_message": None,
            **task_values,
        }
        if command == "generate-next" and invocation.result is not None:
            generation_request = invocation.result.get("generation_request")
            if isinstance(generation_request, dict):
                values["generation_request"] = generation_request
        changed = session.execute(
            update(DomesticMainImageTaskRecord)
            .where(
                DomesticMainImageTaskRecord.id == task.id,
                DomesticMainImageTaskRecord.revision == expected_revision,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if getattr(changed, "rowcount", None) != 1:
            session.rollback()
            raise ApiError(
                409, "STALE_SESSION_REVISION", "任务已由另一个请求推进，请刷新后重试。"
            )
        session.add(
            self._command_record(
                task,
                invocation,
                sequence=sequence,
                committed=next_revision,
                before=before,
            )
        )
        session.commit()
        session.refresh(task)
        return task

    def _bind_identity_paths(
        self,
        session: Session,
        task: DomesticMainImageTaskRecord,
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        sources = session.scalars(
            select(DomesticMainImageSourceRecord)
            .where(DomesticMainImageSourceRecord.task_id == task.id)
            .order_by(DomesticMainImageSourceRecord.ordinal)
        ).all()
        evidence_input = identity.get("evidence")
        if not isinstance(evidence_input, list):
            evidence_input = []
        tags_by_id = {
            str(item.get("evidence_id")): item.get("view_tags", [])
            for item in evidence_input
            if isinstance(item, dict)
        }
        bound = deepcopy(identity)
        bound["request_id"] = task.session_payload["request_id"]
        bound["evidence"] = [
            {
                "evidence_id": source.evidence_id,
                "path": source.runtime_path,
                "view_tags": tags_by_id.get(source.evidence_id) or [source.source_role],
            }
            for source in sources
        ]
        bound["previous_generated_images_used"] = False
        bound["profile01_semantics_read"] = False
        return bound

    def _validate_generation_request(
        self, task: DomesticMainImageTaskRecord
    ) -> dict[str, Any]:
        commands_request = task.session_payload.get("state")
        if commands_request != "AWAITING_GENERATED_ASSET":
            raise DomesticMainImageRuntimeError(
                "GENERATION_CONTRACT_INVALID",
                "Skill did not enter the generation state.",
            )
        if not isinstance(task.generation_request, dict):
            raise DomesticMainImageRuntimeError(
                "GENERATION_CONTRACT_INVALID",
                "Skill did not return a generation request.",
            )
        generation: dict[str, Any] = deepcopy(task.generation_request)
        prompt = generation.get("prompt")
        allowlist = generation.get("reference_allowlist")
        surface = generation.get("output_surface_contract")
        if (
            not isinstance(prompt, str)
            or not prompt
            or not isinstance(allowlist, list)
            or not isinstance(surface, dict)
            or surface.get("aspect_ratio") != "1:1"
            or int(surface.get("minimum_width", 0)) < 1024
            or int(surface.get("minimum_height", 0)) < 1024
        ):
            raise DomesticMainImageRuntimeError(
                "GENERATION_CONTRACT_INVALID",
                "Skill generation contract is incomplete.",
            )
        if any(item.get("role") != "PRODUCT_IDENTITY_AUTHORITY" for item in allowlist):
            raise DomesticMainImageRuntimeError(
                "REFERENCE_ROLE_INVALID",
                "Product identity reference roles were flattened.",
            )
        generation["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return generation

    @staticmethod
    def _next_sequence(session: Session, task_id: str) -> int:
        value = session.scalar(
            select(func.max(DomesticMainImageCommandRecord.sequence)).where(
                DomesticMainImageCommandRecord.task_id == task_id
            )
        )
        return int(value or 0) + 1

    @staticmethod
    def _command_record(
        task: DomesticMainImageTaskRecord,
        invocation: HarnessInvocation,
        *,
        sequence: int,
        committed: int | None,
        before: dict[str, Any] | None = None,
    ) -> DomesticMainImageCommandRecord:
        return DomesticMainImageCommandRecord(
            id=new_id("maincmd"),
            task_id=task.id,
            sequence=sequence,
            command=invocation.command,
            expected_revision=task.revision,
            committed_revision=committed,
            command_input=invocation.command_input,
            argv=list(invocation.argv),
            exit_code=invocation.exit_code,
            stdout=invocation.stdout,
            stderr=invocation.stderr,
            result_payload=invocation.result,
            session_before_sha256=(canonical_json_sha256(before) if before else None),
            session_after_sha256=(
                canonical_json_sha256(invocation.session)
                if invocation.session is not None
                else None
            ),
            transition_committed=committed is not None,
        )

    @staticmethod
    def _failure_message(invocation: HarnessInvocation) -> str:
        if invocation.result and invocation.result.get("error"):
            return str(invocation.result["error"])
        return (
            invocation.stderr.strip() or "Domestic main-image harness command failed."
        )

    @staticmethod
    def _require_success(invocation: HarnessInvocation) -> None:
        if invocation.exit_code != 0 or invocation.session is None:
            raise DomesticMainImageRuntimeError(
                "HARNESS_COMMAND_FAILED",
                DomesticMainImageOrchestrator._failure_message(invocation),
            )
