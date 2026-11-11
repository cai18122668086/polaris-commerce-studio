"""Drive the existing public HTTP workflow for the authorized Tengli demo batch.

No direct database edits or provider access. Reuses durable saved request IDs.
Only the explicit `plan` action can queue the five paid planning requests.
"""

import argparse
import json
import mimetypes
import sys
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import atomic_json, read_json

TEMPLATES = [
    "presenter-openings-v1",
    "rotation-cards-v1",
    "azl-panels-v1",
    "unified-chapter-v1",
    "unified-paper-typewriter-v1",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["setup", "recognize", "align", "prepare", "plan", "status"]
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8018)
    parser.add_argument("--authorized-five-plans", action="store_true")
    args = parser.parse_args()
    root = args.root
    state_path = root / "flow.json"
    state = (
        read_json(state_path)
        if state_path.exists()
        else {
            "project": str(uuid4()),
            "requests": {},
            "materials": {},
            "preparations": {},
            "plans": {},
        }
    )
    c = httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}",
        headers={"X-User-Id": "usr_development"},
        trust_env=False,
        timeout=120,
    )
    api = "/api/v1/video-studio/workspaces/ws_development"
    scripts = read_json(
        Path(__file__).resolve().parents[1] / "docs/tengli-site-demo-scripts.json"
    )

    def save():
        atomic_json(state_path, state)

    def request_id(key):
        if key not in state["requests"]:
            state["requests"][key] = str(uuid4())
            save()
        return state["requests"][key]

    def checked(response):
        if not response.is_success:
            code = response.json().get("error", {}).get("code", "REQUEST_FAILED")
            raise RuntimeError(f"HTTP {response.status_code}: {code}")
        return response.json()

    def get_task(kind, task_id):
        return checked(c.get(api + "/" + kind + "/" + task_id))

    if args.action == "setup":
        project_url = api + "/projects/" + state["project"]
        existing = c.get(project_url)
        if existing.status_code == 404:
            checked(
                c.put(
                    project_url,
                    json={
                        "request_id": request_id("project"),
                        "expected_revision": 0,
                        "content": {
                            "draft": {
                                "name": "腾力网站·四个入口·五款风格对照",
                                "text": scripts["scripts"]["four-goals"]["text"],
                                "avatarId": "qy-model-230",
                                "voiceId": "mm-voice-8c91dd8e0c5d9f440fb7",
                                "quality": "1080P",
                                "drive": "text",
                                "speed": 1.2,
                                "emotion": "自然",
                                "language": "auto",
                            },
                            "product_facts": (
                                "极光商绘电商视觉创作网站；一键复刻、主图套图、"
                                "详情图套图、灵感专区；上传商品原图、补充信息、"
                                "任务中心查看下载。"
                            ),
                            "references": [
                                {
                                    "id": str(uuid4()),
                                    "kind": "url",
                                    "url": "https://www.tengliapi.xyz/",
                                    "note": "2026-11-11 实际首页功能核对",
                                }
                            ],
                        },
                    },
                )
            )
        else:
            checked(existing)
        if not state.get("source"):
            media = root / "source/tengli-four-goals-original.mp4"
            with media.open("rb") as file:
                source = checked(
                    c.post(
                        api + "/editing-sources",
                        data={"project_id": state["project"]},
                        files={"file": (media.name, file, "video/mp4")},
                    )
                )
            state["source"] = source["id"]
            atomic_json(root / "uploaded-source.json", source)
            save()
        assets = root.parent / "site-assets"
        for tag, name, label, description in [
            (
                "replica",
                "replica-01.png",
                "一键复刻公开案例",
                "极光商绘官网一键复刻入口展示的 OLAY 商品案例。"
                "用于讲参考构图和风格，属于公开示例，不是客户证言。",
            ),
            (
                "main",
                "05-domestic-primary-desktop.webp",
                "主图套图官网案例",
                "极光商绘官网国内主图功能示例，用于说明搜索主图和轮播的任务。只作为官网作品示例，不是操作录屏。",
            ),
            (
                "detail",
                "04-detail-primary-desktop.webp",
                "详情图套图官网案例",
                "极光商绘官网详情图功能示例，用于说明细节和场景的连续视觉内容。不是生成过程或客户证言。",
            ),
            (
                "inspiration",
                "try-on-result.png",
                "灵感参考·商品试穿案例",
                "极光商绘官网商品试穿效果案例，可作为创作方向参考。不可当作上传或任务中心的操作录屏。",
            ),
        ]:
            if tag in state["materials"]:
                continue
            path = assets / name
            with path.open("rb") as file:
                row = checked(
                    c.post(
                        api + f"/projects/{state['project']}/editing-materials",
                        data={
                            "request_id": request_id("material:" + tag),
                            "label": label,
                            "description": description,
                        },
                        files={
                            "file": (
                                path.name,
                                file,
                                mimetypes.guess_type(path.name)[0] or "image/png",
                            )
                        },
                    )
                )
            state["materials"][tag] = row["id"]
            save()
        print(
            json.dumps(
                {
                    "project": state["project"],
                    "source": state["source"],
                    "materials": len(state["materials"]),
                    "provider_calls": 0,
                }
            )
        )
    elif args.action == "recognize":
        if not state.get("recognition"):
            row = checked(
                c.post(
                    api + "/editing-tasks",
                    json={
                        "request_id": request_id("recognition"),
                        "source_id": state["source"],
                        "options": {"mode": "transcript", "source_subtitles": "none"},
                    },
                )
            )
            state["recognition"] = row["id"]
            save()
        print(json.dumps(get_task("editing-tasks", state["recognition"])))
    elif args.action == "align":
        row = get_task("editing-tasks", state["recognition"])
        if row["status"] != "completed":
            raise ValueError("Wait for real recognition before correcting and aligning")
        transcript = checked(c.get(api + f"/editing-tasks/{row['id']}/transcript"))
        atomic_json(root / "recognized.json", transcript)
        if not state.get("revision"):
            revision = checked(
                c.post(
                    api + f"/editing-tasks/{row['id']}/transcript-revisions",
                    json={
                        "request_id": request_id("revision"),
                        "base_transcript_artifact_id": transcript["artifact_id"],
                        "corrected_text": scripts["scripts"]["four-goals"]["text"],
                    },
                )
            )
            state["revision"] = revision["id"]
            save()
        if not state.get("alignment"):
            aligned = checked(
                c.post(
                    api + "/editing-tasks",
                    json={
                        "request_id": request_id("alignment"),
                        "source_id": state["source"],
                        "options": {
                            "mode": "transcript",
                            "source_subtitles": "none",
                            "transcript_revision_id": state["revision"],
                        },
                    },
                )
            )
            state["alignment"] = aligned["id"]
            save()
        print(json.dumps(get_task("editing-tasks", state["alignment"])))
    elif args.action == "prepare":
        assert get_task("editing-tasks", state["alignment"])["status"] == "completed"
        aligned = checked(
            c.get(api + f"/editing-tasks/{state['alignment']}/transcript")
        )
        atomic_json(root / "aligned.json", aligned)
        for tid in TEMPLATES:
            if tid not in state["preparations"]:
                row = checked(
                    c.post(
                        api + f"/editing-tasks/{state['alignment']}/planning-tasks",
                        json={
                            "request_id": request_id("prepare:" + tid),
                            "template_id": tid,
                            "material_ids": list(state["materials"].values()),
                        },
                    )
                )
                state["preparations"][tid] = row["id"]
                save()
        print(json.dumps({"free_preparations": len(state["preparations"])}))
    elif args.action == "plan":
        if not args.authorized_five_plans:
            raise ValueError(
                "Explicit authorization flag required for these five paid calls"
            )
        preparations = {
            tid: get_task("editing-planning-tasks", state["preparations"][tid])
            for tid in TEMPLATES
        }
        for tid, row in preparations.items():
            assert row["status"] == "prepared" and not row.get(
                "template_style_blockers"
            ), tid
        for tid in TEMPLATES:
            if tid not in state["plans"]:
                row = checked(
                    c.post(
                        api + f"/editing-tasks/{state['alignment']}/planning-tasks",
                        json={
                            "request_id": request_id("plan:" + tid),
                            "mode": "generate",
                            "prepared_task_id": state["preparations"][tid],
                            "auto_preview": True,
                        },
                    )
                )
                state["plans"][tid] = row["id"]
                save()
        print(json.dumps({"authorized_planning_tasks": len(state["plans"])}))
    else:
        summary = {}
        for phase, ids in [
            ("preparations", state["preparations"]),
            ("plans", state["plans"]),
        ]:
            summary[phase] = {}
            for tid, task_id in ids.items():
                row = get_task("editing-planning-tasks", task_id)
                result = {
                    k: row.get(k)
                    for k in [
                        "id",
                        "status",
                        "stage",
                        "error_code",
                        "request_bytes",
                        "motion_counts",
                        "template_style_blockers",
                        "preview_task_id",
                        "auto_preview_error_code",
                    ]
                }
                if row.get("preview_task_id"):
                    result["preview"] = {
                        k: v
                        for k, v in get_task(
                            "editing-tasks", row["preview_task_id"]
                        ).items()
                        if k in {"status", "stage", "error_code", "revision"}
                    }
                summary[phase][tid] = result
        atomic_json(root / "flow-status.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
