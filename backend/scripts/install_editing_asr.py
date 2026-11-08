"""Fetch only pinned official model files; safe to rerun without re-downloading."""

import argparse
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

from app.motion_library import inside, read_json, sha256
from app.video_editing_funasr import MANIFEST, bundle_identity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--bundle", choices=["recognition", "alignment"], default="recognition"
    )
    args = parser.parse_args()
    manifest = (
        MANIFEST
        if args.bundle == "recognition"
        else MANIFEST.with_name("editing_alignment_models.json")
    )
    with httpx.Client(
        timeout=httpx.Timeout(90, connect=20), follow_redirects=True
    ) as client:
        for name, model in read_json(manifest)["models"].items():
            for item in model["files"]:
                path = inside(args.root / name, item["Path"])
                if path.is_file() and sha256(path) == item["Sha256"]:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".download")
                query = urlencode(
                    {"Revision": item["Revision"], "FilePath": item["Path"]}
                )
                url = (
                    "https://modelscope.cn/api/v1/models/"
                    + quote(model["model_id"], safe="/")
                    + "/repo?"
                    + query
                )
                size = 0
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as output:
                        for block in response.iter_bytes(1024 * 1024):
                            size += len(block)
                            if size > item["Size"]:
                                raise ValueError("Model download exceeded pinned size")
                            output.write(block)
                if size != item["Size"] or sha256(temporary) != item["Sha256"]:
                    raise ValueError("Model download integrity failed")
                temporary.replace(path)
                print("Verified", name, item["Path"], flush=True)
    print("Pinned bundle verified:", bundle_identity(args.root, manifest_path=manifest))


if __name__ == "__main__":
    main()
