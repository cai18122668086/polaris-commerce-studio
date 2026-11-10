"""Serve frozen supplemental bytes through the original browser's loopback server."""

import importlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .motion_browser_originals import (
    BROWSER_ORIGINALS_KEY,
    RENDER_GROUPS,
    browser_original_evidence,
    require_browser_originals,
    verified_image_bytes,
)
from .motion_library import inside, read_json, sha256
from .video_editing_browser_clocks import SPLIT_WRAPPER_SHA


def _server_with_originals(
    selected: dict[str, dict[str, str]], served: set[str]
) -> type[ThreadingHTTPServer]:
    class BrowserOriginalServer(ThreadingHTTPServer):
        def __init__(self, address: tuple[str, int], handler: Any) -> None:
            if address != ("127.0.0.1", 0):
                raise ValueError("Expected the original instance loopback server")

            def get(request: BaseHTTPRequestHandler) -> None:
                path = unquote(urlsplit(request.path).path).removeprefix("/")
                row = selected.get(path)
                if row is None:
                    handler.do_GET(request)
                    return
                try:
                    data = verified_image_bytes(Path(row["path"]), row["sha256"])
                except (OSError, ValueError):
                    request.send_error(409, "Frozen original image changed")
                    return
                kind = "image/jpeg" if path.endswith(".jpg") else "image/png"
                served.add(path)
                request.send_response(200)
                request.send_header("Content-Type", kind)
                request.send_header("Content-Length", str(len(data)))
                request.end_headers()
                request.wfile.write(data)

            verified_handler = type(
                "BrowserOriginalHandler", (handler,), {"do_GET": get}
            )
            super().__init__(address, verified_handler)

    return BrowserOriginalServer


def install_browser_originals(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    job = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job.parent != root / "plans":
        return
    group_id = read_json(job)["group_id"]
    if group_id not in RENDER_GROUPS:
        return
    frozen = read_json(root / "bindings.json").get(BROWSER_ORIGINALS_KEY)
    if not frozen:
        return
    entry = package / "commercial_runtime/special.py"
    if sha256(entry) != SPLIT_WRAPPER_SHA:
        raise ValueError("Original browser loopback loader changed")
    sys.path.insert(0, str(package))
    try:
        special: Any = importlib.import_module("commercial_runtime.special")
    finally:
        sys.path.pop(0)
    if Path(special.__file__).resolve() != entry:
        raise ValueError("Supplemental originals need the pinned browser loader")
    original_drawer = special.browser_drawer

    def draw(card: dict, config: dict) -> tuple[Any, dict]:
        if card["id"] != group_id:
            return original_drawer(card, config)
        selected = require_browser_originals(
            package, card, config, frozen, root / "browser-originals"
        )
        if not selected:
            return original_drawer(card, config)
        expected = read_json(package / "integrity.json")["files"][card["entry"]]
        if sha256(inside(package, card["entry"])) != expected:
            raise ValueError("Original browser draw source changed")
        prefix = card["browser_directory"] + "/"
        served: set[str] = set()
        local = {name.removeprefix(prefix): row for name, row in selected.items()}
        server = special.ThreadingHTTPServer
        if server is not ThreadingHTTPServer:
            raise ValueError("Original browser server class changed")
        special.ThreadingHTTPServer = _server_with_originals(local, served)
        try:
            render, meta = original_drawer(card, config)
        finally:
            special.ThreadingHTTPServer = server
        if served != local.keys():
            raise ValueError("Original browser did not load every frozen active image")
        return render, {
            **meta,
            BROWSER_ORIGINALS_KEY: browser_original_evidence(selected),
        }

    special.browser_drawer = draw
