"""Private, bounded per-image staging on the shared generation work volume."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from uuid import uuid4

from .errors import ApiError
from .storage import (
    STORAGE_WRITE_MESSAGE,
    STORAGE_WRITE_UNAVAILABLE,
    ImageStorage,
    ValidatedImage,
)

logger = logging.getLogger(__name__)


class GenerationImageStage:
    def __init__(self, root: Path, pipeline: str) -> None:
        self.root = root / "delivery-spool" / pipeline

    def path(self, workspace: str, job: str, attempt: str) -> Path:
        scope = hashlib.sha256(f"{workspace}\0{job}\0{attempt}".encode()).hexdigest()
        return self.root / scope[:2] / scope

    def require_writable(self, maximum: int) -> None:
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if shutil.disk_usage(self.root).free < maximum:
                raise OSError("Insufficient space for one generation result")
            probe = self.root / (".probe-" + uuid4().hex)
            try:
                with probe.open("xb") as stream:
                    stream.write(b"polaris")
            finally:
                probe.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Generation staging volume is not writable: %s", error)
            raise ApiError(
                503,
                STORAGE_WRITE_UNAVAILABLE,
                STORAGE_WRITE_MESSAGE,
            ) from error

    def save(self, path: Path, image: ValidatedImage, maximum: int) -> None:
        if not image.payload or len(image.payload) > maximum:
            raise ValueError("Generated image is outside the staging size limit")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with os.fdopen(
                os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
            ) as stream:
                stream.write(image.payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name == "posix":
                descriptor = os.open(
                    path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, path: Path, maximum: int) -> bytes:
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        if not data or len(data) > maximum:
            raise ValueError("Staged image is outside the size limit")
        return data

    @staticmethod
    def discard(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove delivered generation stage", exc_info=True)


async def staged_or_stored(
    storage: ImageStorage,
    stage: GenerationImageStage | None,
    path: Path | None,
    object_key: str,
    sha256: str,
) -> tuple[bytes, bool]:
    if stage is not None and path is not None:
        try:
            data = stage.read(path, storage.validator.max_upload_bytes)
        except FileNotFoundError:
            pass
        else:
            if hashlib.sha256(data).hexdigest() != sha256:
                raise ValueError("Staged generation checksum is invalid")
            return data, True
    data = await storage.read_bytes(object_key)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("Stored generation checksum is invalid")
    return data, False
