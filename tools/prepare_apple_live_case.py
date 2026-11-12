"""Create a fresh local real-provider case without submitting generation."""

import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json
from app.video_providers import VideoProviders
from app.video_template_media import video_info
from tengli_site_demo_runtime import settings_for

ROOT = Path("C:/tl/bihuo-editing-20261112/live-case-v1")
TEXT = (
    "新品上架前，商品图先检查这三件事。"
    "先看主图，产品是否清楚，核心卖点能不能一眼看懂。"
    "再看详情，规格和使用场景有没有讲完整。"
    "最后看整套图片，颜色和排版是不是统一。"
    "检查完成，再导出预览，逐张核对。"
    "把图片讲清楚，顾客才能更快看懂你的产品。"
)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "site.db").exists():
        original = Path("C:/tl/bihuo-editing-20261112/runtime/site.db")
        with (
            sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as source,
            sqlite3.connect(ROOT / "site.db") as target,
        ):
            source.backup(target)
    settings = settings_for(
        ROOT, Path("D:/Desktop/cyh/tengli/polaris-commerce-studio/backend/.env")
    )
    provider = VideoProviders(settings)
    selected = next(m for m in provider.models() if m["id"] == 255)
    assert selected["is_public"] and selected["is_active"]
    source = ROOT / "public-presenter.mp4"
    if not source.exists():
        provider.download(selected["video_url"], source)
    info = video_info(source)
    record = {
        "scope": "one new public presenter and script through real website generation and editing",
        "project_name": "新人物新稿·商品图上架检查·真实链路",
        "script": TEXT,
        "avatar_id": "qy-model-255",
        "avatar_name": selected["model_name"],
        "public_model": True,
        "source_info": info,
        "paid_generation_submitted": False,
    }
    state_path = ROOT / "case.json"
    if state_path.exists():
        record.update(json.loads(state_path.read_text(encoding="utf8")))
    if "--install-project" in sys.argv and not record.get("project_id"):
        project_id = str(uuid4())
        with httpx.Client(
            base_url="http://127.0.0.1:8019",
            headers={"X-User-Id": "usr_development"},
            timeout=60,
            trust_env=False,
        ) as client:
            response = client.put(
                f"/api/v1/video-studio/workspaces/ws_development/projects/{project_id}",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "content": {
                        "draft": {
                            "name": record["project_name"],
                            "text": TEXT,
                            "avatarId": "qy-model-255",
                            "voiceId": "mm-voice-8e4b39927e9adc9fc684",
                            "quality": "1080P",
                            "drive": "text",
                            "speed": 1.1,
                            "emotion": "自然",
                            "language": "auto",
                        }
                    },
                },
            )
            response.raise_for_status()
        record["project_id"] = project_id
    atomic_json(state_path, record)
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
