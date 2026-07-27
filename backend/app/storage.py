import asyncio
import hashlib
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
    object_key: str
    sha256: str
    storage_provider: str
    storage_bucket: str
    object_version: str = ""
    etag: str | None = None


@dataclass(frozen=True)
class ValidatedImage:
    payload: bytes
    filename: str
    content_type: str
    width: int
    height: int
    object_key: str
    sha256: str


class ImageStorage(Protocol):
    provider_name: str
    bucket_name: str

    async def save_image(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> StoredImage: ...

    async def save_validated(self, image: ValidatedImage) -> StoredImage: ...

    async def delete_object(
        self,
        object_key: str,
        object_version: str = "",
    ) -> None: ...

    async def read_bytes(self, object_key: str) -> bytes: ...

    async def create_access_url(
        self,
        object_key: str,
        filename: str,
        disposition: str,
        expires_seconds: int,
    ) -> str | None: ...


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
            object_key=f"{workspace_id}/{uuid4().hex}{suffix}",
            sha256=hashlib.sha256(payload).hexdigest(),
        )


class LocalImageStorage:
    def __init__(
        self,
        root: Path,
        validator: ImageValidator,
    ) -> None:
        self.root = root.resolve()
        self.validator = validator
        self.provider_name = "local"
        self.bucket_name = "local"

    async def save_image(
        self,
        upload: UploadFile,
        workspace_id: str,
    ) -> StoredImage:
        image = await self.validator.validate(upload, workspace_id)
        return await self.save_validated(image)

    async def save_validated(self, image: ValidatedImage) -> StoredImage:
        destination = (self.root / image.object_key).resolve()
        self._require_safe_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, image.payload)
        return _stored_image(
            image,
            provider=self.provider_name,
            bucket=self.bucket_name,
        )

    async def delete_object(
        self,
        object_key: str,
        object_version: str = "",
    ) -> None:
        del object_version
        destination = (self.root / object_key).resolve()
        self._require_safe_path(destination)
        await asyncio.to_thread(destination.unlink, missing_ok=True)

    async def read_bytes(self, object_key: str) -> bytes:
        source = (self.root / object_key).resolve()
        if self.root not in source.parents:
            raise FileNotFoundError(object_key)
        return await asyncio.to_thread(source.read_bytes)

    def _require_safe_path(self, path: Path) -> None:
        if self.root not in path.parents:
            raise UploadValidationError(
                "INVALID_STORAGE_PATH",
                "无法创建安全的文件存储路径。",
            )

    async def create_access_url(
        self,
        object_key: str,
        filename: str,
        disposition: str,
        expires_seconds: int,
    ) -> str | None:
        del object_key, filename, disposition, expires_seconds
        return None


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
        auto_create_bucket: bool = False,
    ) -> None:
        self.bucket = bucket
        self.bucket_name = bucket
        self.provider_name = "s3"
        self.validator = validator
        self.auto_create_bucket = auto_create_bucket
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
        return await self.save_validated(image)

    async def save_validated(self, image: ValidatedImage) -> StoredImage:
        result = await asyncio.to_thread(self._put_image, image)
        raw_etag = result.get("ETag")
        return _stored_image(
            image,
            provider=self.provider_name,
            bucket=self.bucket,
            etag=str(raw_etag).strip('"') if raw_etag else None,
            version=str(result.get("VersionId") or ""),
        )

    def _put_image(self, image: ValidatedImage) -> dict[str, object]:
        self._ensure_bucket()
        result = self.client.put_object(
            Bucket=self.bucket,
            Key=image.object_key,
            Body=image.payload,
            ContentType=image.content_type,
            Metadata={
                "workspace-id": image.object_key.split("/", 1)[0],
                "sha256": image.sha256,
            },
        )
        return dict(result)

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            if not self.auto_create_bucket:
                raise RuntimeError(
                    f"对象存储桶 {self.bucket!r} 不存在，且禁止在请求路径自动创建。"
                ) from exc
            self.client.create_bucket(Bucket=self.bucket)
        self._bucket_ready = True

    async def delete_object(
        self,
        object_key: str,
        object_version: str = "",
    ) -> None:
        await asyncio.to_thread(self._delete_object, object_key, object_version)

    def _delete_object(self, object_key: str, object_version: str) -> None:
        request: dict[str, str] = {
            "Bucket": self.bucket,
            "Key": object_key,
        }
        if object_version:
            request["VersionId"] = object_version
        self.client.delete_object(**request)

    async def read_bytes(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.bucket,
            Key=object_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    async def create_access_url(
        self,
        object_key: str,
        filename: str,
        disposition: str,
        expires_seconds: int,
    ) -> str | None:
        content_disposition = f'{disposition}; filename="{_safe_filename(filename)}"'
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
                "ResponseContentDisposition": content_disposition,
            },
            ExpiresIn=expires_seconds,
        )


def _stored_image(
    image: ValidatedImage,
    *,
    provider: str,
    bucket: str,
    version: str = "",
    etag: str | None = None,
) -> StoredImage:
    return StoredImage(
        filename=image.filename,
        content_type=image.content_type,
        byte_size=len(image.payload),
        width=image.width,
        height=image.height,
        object_key=image.object_key,
        sha256=image.sha256,
        storage_provider=provider,
        storage_bucket=bucket,
        object_version=version,
        etag=etag,
    )


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    return cleaned[:120] or "download"
