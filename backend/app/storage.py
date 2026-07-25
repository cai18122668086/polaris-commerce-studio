import asyncio
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from .errors import UploadValidationError

ALLOWED_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


@dataclass(frozen=True)
class StoredImage:
    filename: str
    content_type: str
    byte_size: int
    width: int
    height: int
    storage_key: str


@dataclass(frozen=True)
class ValidatedImage:
    payload: bytes
    filename: str
    content_type: str
    width: int
    height: int
    storage_key: str


class ImageStorage(Protocol):
    async def save_image(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> StoredImage: ...


class ImageValidator:
    def __init__(self, max_upload_bytes: int, max_image_pixels: int) -> None:
        self.max_upload_bytes = max_upload_bytes
        self.max_image_pixels = max_image_pixels

    async def validate(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> ValidatedImage:
        payload = await upload.read(self.max_upload_bytes + 1)
        if not payload:
            raise UploadValidationError("EMPTY_FILE", "上传文件不能为空。")
        if len(payload) > self.max_upload_bytes:
            raise UploadValidationError(
                "FILE_TOO_LARGE",
                f"图片不能超过 {self.max_upload_bytes // (1024 * 1024)}MB。",
            )

        try:
            with Image.open(BytesIO(payload)) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise UploadValidationError(
                "INVALID_IMAGE",
                "文件不是可识别的 PNG、JPEG 或 WebP 图片。",
            ) from exc

        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise UploadValidationError(
                "UNSUPPORTED_IMAGE_TYPE",
                "仅支持 PNG、JPEG 和 WebP 图片。",
            )
        if width * height > self.max_image_pixels:
            raise UploadValidationError(
                "IMAGE_DIMENSIONS_TOO_LARGE",
                "图片像素总量超过当前限制。",
            )

        if not re.fullmatch(r"[A-Za-z0-9_-]+", workspace_id):
            raise UploadValidationError(
                "INVALID_WORKSPACE_ID",
                "工作区标识格式不正确。",
            )

        suffix, content_type = ALLOWED_IMAGE_FORMATS[image_format]
        filename = Path(upload.filename or f"upload{suffix}").name[:255]
        return ValidatedImage(
            payload=payload,
            filename=filename,
            content_type=content_type,
            width=width,
            height=height,
            storage_key=f"{workspace_id}/{uuid4().hex}{suffix}",
        )


class LocalImageStorage:
    def __init__(
        self,
        root: Path,
        validator: ImageValidator,
    ) -> None:
        self.root = root.resolve()
        self.validator = validator

    async def save_image(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> StoredImage:
        image = await self.validator.validate(upload, workspace_id)
        destination = (self.root / image.storage_key).resolve()
        if self.root not in destination.parents:
            raise UploadValidationError(
                "INVALID_STORAGE_PATH",
                "无法创建安全的文件存储路径。",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, image.payload)
        return _stored_image(image)


class S3ImageStorage:
    def __init__(
        self,
        *,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        validator: ImageValidator,
    ) -> None:
        self.bucket = bucket
        self.validator = validator
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._bucket_ready = False

    async def save_image(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> StoredImage:
        image = await self.validator.validate(upload, workspace_id)
        await asyncio.to_thread(self._put_image, image)
        return _stored_image(image)

    def _put_image(self, image: ValidatedImage) -> None:
        self._ensure_bucket()
        self.client.put_object(
            Bucket=self.bucket,
            Key=image.storage_key,
            Body=image.payload,
            ContentType=image.content_type,
            Metadata={"workspace-id": image.storage_key.split("/", 1)[0]},
        )

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)
        self._bucket_ready = True


def _stored_image(image: ValidatedImage) -> StoredImage:
    return StoredImage(
        filename=image.filename,
        content_type=image.content_type,
        byte_size=len(image.payload),
        width=image.width,
        height=image.height,
        storage_key=image.storage_key,
    )
