from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from io import BytesIO

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from app.errors import UploadValidationError
from app.storage import (
    ImageValidator,
    LocalImageStorage,
    S3ImageStorage,
)
from app.thumbnails import render_thumbnail
from tests.test_api import WORKSPACE_ID, idem


def exif_image(image_format: str, orientation: int) -> bytes:
    image = Image.new("RGB", (120, 80), "#315a88")
    image.paste("#fa7030", (0, 0, 35, 25))
    exif = Image.Exif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, format=image_format, exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("backend", ["local", "s3"])
@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_upload_keeps_original_bytes_and_encoded_dimensions(
    tmp_path, monkeypatch, backend, image_format, orientation,
):
    payload = exif_image(image_format, orientation)
    validator = ImageValidator(20_000_000, 6_000_000)
    if backend == "local":
        storage = LocalImageStorage(tmp_path, validator)
    else:
        storage = object.__new__(S3ImageStorage)
        storage.validator = validator
        storage.bucket = storage.bucket_name = "test-bucket"
        storage.provider_name = "s3"
        written = []

        def put(image):
            written.append(image.payload)
            return {"ETag": '"test-etag"'}

        monkeypatch.setattr(storage, "_put_image", put)
    upload = UploadFile(file=BytesIO(payload), filename="phone-photo.jpg")

    stored = asyncio.run(storage.save_image(upload, WORKSPACE_ID))

    assert (stored.width, stored.height) == (120, 80)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.byte_size == len(payload)
    if backend == "local":
        assert (tmp_path / stored.object_key).read_bytes() == payload
    else:
        assert written == [payload]
    # Preview follows EXIF without changing the immutable stored original.
    with Image.open(BytesIO(render_thumbnail(payload))) as thumbnail:
        assert thumbnail.size == ((80, 120) if orientation >= 5 else (120, 80))


@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_upload_api_accepts_rotated_exif_photo(client, orientation):
    payload = exif_image("JPEG", orientation)
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers=idem(), files={"file": ("phone-photo.jpg", payload, "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert (asset["width"], asset["height"]) == (120, 80)
    assert asset["sha256"] == hashlib.sha256(payload).hexdigest()


def test_exif_does_not_allow_forged_prepared_dimensions(tmp_path):
    validator = ImageValidator(20_000_000, 6_000_000)
    storage = LocalImageStorage(tmp_path, validator)
    payload = exif_image("JPEG", 6)
    prepared = asyncio.run(validator.validate(
        UploadFile(file=BytesIO(payload), filename="phone-photo.jpg"), WORKSPACE_ID,
    ))
    with pytest.raises(UploadValidationError) as caught:
        asyncio.run(storage.save_validated(replace(prepared, width=80, height=120)))
    assert caught.value.code == "IMAGE_DIMENSIONS_MISMATCH"
    assert not list(tmp_path.rglob("*.jpg"))


def test_upload_api_returns_400_when_full_decode_finds_truncated_jpeg(client):
    payload = exif_image("JPEG", 1)[:-20]
    with Image.open(BytesIO(payload)) as header:
        header.verify()
    with Image.open(BytesIO(payload)) as image, pytest.raises(OSError):
        image.load()
    http = TestClient(client.app, raise_server_exceptions=False)
    try:
        response = http.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/assets", headers=idem(),
            files={"file": ("truncated.jpg", payload, "image/jpeg")},
        )
    finally:
        http.close()
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_IMAGE"
