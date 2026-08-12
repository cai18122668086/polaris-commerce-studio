"""Zero-side-effect Xinghe request compiler for Aurora generation requests."""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .aurora_detail_runtime import (
    GenerationEnvelope,
    GenerationProviderCapabilities,
    assert_provider_receipt,
    compile_generation_envelope,
)
from .xinghe_agent import ImageEditRequest, SourceImage, XingheGateway


@dataclass(frozen=True)
class PreparedAuroraImageCall:
    envelope: GenerationEnvelope
    request: ImageEditRequest


class XingheAuroraRequestCompiler:
    """Compile, but never execute, the exact billable provider request."""

    endpoint = "v1/images/edits"

    def __init__(self, gateway: XingheGateway, *, model_version: str) -> None:
        version = model_version.strip()
        if not version:
            raise ValueError("A pinned Aurora image model version is required.")
        self.gateway = gateway
        self.model_version = version

    def prepare(
        self,
        generation_request: Mapping[str, Any],
        session: Mapping[str, Any],
        *,
        workspace_id: str,
        job_id: str,
        job_item_id: str,
        attempt_id: str,
        page_number: int,
        idempotency_key: str,
    ) -> PreparedAuroraImageCall:
        parameters = {
            "quality": "high",
            "output_format": "png",
            "jpeg_quality": 100,
            "preserve_provider_artifact": True,
        }
        envelope = compile_generation_envelope(
            generation_request,
            session,
            capabilities=GenerationProviderCapabilities(
                ordered_references=True,
                primary_edit_image=True,
                fixed_model_version=True,
                idempotency=True,
                request_recovery=True,
            ),
            model=self.gateway.image_model,
            model_version=self.model_version,
            endpoint=self.endpoint,
            parameters=parameters,
            idempotency_key=idempotency_key,
        )
        ordered_paths = list(envelope.reference_images)
        roles = ["ordered_reference"] * len(ordered_paths)
        if envelope.edit_target is not None:
            ordered_paths.insert(0, envelope.edit_target)
            roles.insert(0, "primary_edit_image")
        sources = tuple(
            _source_from_path(path, role, ordinal)
            for ordinal, (path, role) in enumerate(
                zip(ordered_paths, roles, strict=True)
            )
        )
        width, height = _current_dimensions(session, envelope.module_id)
        provider_request = ImageEditRequest(
            workspace_id=workspace_id,
            job_id=job_id,
            job_item_id=job_item_id,
            attempt_id=attempt_id,
            page_number=page_number,
            group_key=envelope.module_id,
            sources=sources,
            prompt=envelope.prompt,
            quality="high",
            idempotency_key=envelope.idempotency_key,
            size=f"{width}x{height}",
            output_format="png",
            jpeg_quality=100,
            preserve_provider_artifact=True,
        )
        reference_offset = 1 if envelope.edit_target is not None else 0
        assert_provider_receipt(
            envelope,
            prompt_sha256=_text_sha256(provider_request.prompt),
            ordered_reference_sha256=tuple(
                source.sha256 for source in provider_request.sources[reference_offset:]
            ),
            edit_target_sha256=(
                provider_request.sources[0].sha256
                if envelope.edit_target is not None
                else None
            ),
            model=self.gateway.image_model,
            model_version=self.model_version,
            endpoint=self.endpoint,
            parameters=parameters,
        )
        return PreparedAuroraImageCall(envelope=envelope, request=provider_request)


def _source_from_path(path_value: str, role: str, ordinal: int) -> SourceImage:
    import hashlib

    path = Path(path_value)
    payload = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return SourceImage(
        asset_id=f"aurora-{role}-{ordinal}-{hashlib.sha256(payload).hexdigest()[:12]}",
        group_key="aurora-detail",
        filename=path.name,
        content_type=content_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        payload=payload,
        source_role=role,
    )


def _current_dimensions(
    session: Mapping[str, Any], module_id: str
) -> tuple[int, int]:
    modules = session.get("modules")
    if not isinstance(modules, list):
        raise ValueError("Aurora session modules are unavailable.")
    for module in modules:
        if not isinstance(module, Mapping) or module.get("id") != module_id:
            continue
        plan = module.get("plan")
        output = plan.get("output") if isinstance(plan, Mapping) else None
        width = output.get("width_px") if isinstance(output, Mapping) else None
        height = output.get("height_px") if isinstance(output, Mapping) else None
        if isinstance(width, int) and isinstance(height, int):
            return width, height
    raise ValueError("Aurora module dimensions are unavailable.")


def _text_sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
