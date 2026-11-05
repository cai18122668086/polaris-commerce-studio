"""Editing-side reference client. Token comes from environment, never arguments."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx


def fetch_handoff(base, handoff_id, token, output, *, transport=None):
    parts = urlsplit(base)
    if (
        parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or (
            parts.scheme != "https"
            and not (
                parts.scheme == "http"
                and parts.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise ValueError("Use HTTPS, or loopback HTTP for local acceptance")
    handoff_id = str(UUID(handoff_id))
    prefix = f"/api/v1/video-studio/editing-handoffs/{handoff_id}"
    output = Path(output).resolve() / handoff_id
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url=base.rstrip("/"),
        headers={"Authorization": "Bearer " + token},
        follow_redirects=False,
        timeout=120,
        transport=transport,
    ) as client:
        result = client.get(prefix + "/manifest")
        result.raise_for_status()
        manifest = result.json()
        for kind in ["video", "audio", "script"]:
            if kind == "script" and not manifest["files"]["script"]:
                continue
            route = manifest["assets"][kind]
            if route != prefix + "/assets/" + kind:
                raise ValueError("Unexpected asset path; token was not forwarded")
            name = manifest["files"][kind]
            if Path(name).name != name:
                raise ValueError("Invalid asset filename")
            target = output / name
            temporary = target.with_suffix(target.suffix + ".part")
            digest, count = hashlib.sha256(), 0
            try:
                with client.stream("GET", route) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as file:
                        for chunk in response.iter_bytes():
                            count += len(chunk)
                            if count > 200 * 1024 * 1024:
                                raise ValueError("Asset exceeds supported size")
                            digest.update(chunk)
                            file.write(chunk)
                expected = (
                    manifest["script_sha256"]
                    if kind == "script"
                    else manifest[kind + "_format"]["sha256"]
                )
                if digest.hexdigest() != expected:
                    raise ValueError("Asset digest does not match manifest")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff-id", required=True)
    parser.add_argument("--output", default="editing-inputs")
    args = parser.parse_args()
    token = os.environ.get("VIDEO_EDITING_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("VIDEO_EDITING_ACCESS_TOKEN is required")
    try:
        folder = fetch_handoff(
            os.environ.get("VIDEO_EDITING_BASE_URL", "http://localhost:8013"),
            args.handoff_id,
            token,
            args.output,
        )
        print("Editing materials verified:", folder)
    except httpx.HTTPError as error:
        raise SystemExit(
            "Handoff HTTP request failed; check access and expiry"
        ) from error
