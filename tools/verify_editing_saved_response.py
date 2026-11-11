"""Local captured-response regression; no credentials are loaded. Requires the documented Motion installation."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import Settings
from app.main import create_app
from app.motion_library import atomic_json, read_json, sha256, verify_package
from app.video_editing_materials import PREFIX, SUFFIXES
from app.video_editing_native_plans import content_digest
from app.video_editing_overlay_templates import motion_counts
from app.video_editing_task_models import (
    EditingArtifactRecord,
    EditingMaterialRecord,
    EditingNativePlanRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
)

parser = argparse.ArgumentParser(
    description="Revalidate a saved genuine gateway response and render with zero provider calls"
)
parser.add_argument("--case", choices=("product", "knowledge"), required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--capture-root", type=Path, required=True)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--business-capture", type=Path)
parser.add_argument("--planning-id")
args = parser.parse_args()
case = args.case
root = args.output.resolve() / ("business" if args.business_capture else case)
root.mkdir(parents=True)  # Refuse to overwrite an existing run.
origin = args.business_capture or args.capture_root / case
archive = args.archive
if args.business_capture:
    if not args.planning_id:
        parser.error("--planning-id required for a business capture")
    with sqlite3.connect(
        (origin / "site.db").as_uri() + "?mode=ro", uri=True
    ) as source_connection:
        captured = source_connection.execute(
            "select workspace_id,owner_user_id,project_id from video_editing_planning_tasks where id=?",
            (args.planning_id,),
        ).fetchone()
        assert captured
    ids = dict(
        zip(("workspace", "owner", "project"), captured), planning=args.planning_id
    )
else:
    ids = read_json(origin / "submitted.json")
source_db = (
    origin / "site.db"
    if args.business_capture
    else archive / ("site.db" if case == "product" else "knowledge.db")
)
old_tasks, new_tasks = origin / "tasks", root / "tasks"
db = root / "site.db"
db_sha = sha256(source_db)
with (
    sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as before,
    sqlite3.connect(db) as after,
):
    before.backup(after)
    if args.business_capture:
        # Official 0051 adds these nullable provenance columns to pre-0051 captures.
        for table in ("video_projects", "video_script_versions"):
            columns = {
                row[1] for row in after.execute("pragma table_info(" + table + ")")
            }
            if "writing_origin" not in columns:
                after.execute(
                    "alter table " + table + " add column writing_origin JSON"
                )
        after.commit()
settings = Settings(
    _env_file=None,
    environment="test",
    auth_mode="development",
    development_user_email="1474953130@qq.com",
    auto_create_schema=False,
    auto_process_jobs=False,
    ecommerce_startup_recovery_enabled=False,
    storage_backend="local",
    storage_dir=root / "storage",
    database_url="sqlite:///" + db.as_posix(),
    video_editing_enabled=True,
    video_editing_native_plan_enabled=True,
    video_editing_planning_enabled=False,
    video_editing_template_examples_dir=args.output.resolve() / "examples",
    video_script_planning_enabled=False,
    video_editing_library_dir=Path(
        "C:/tl/clean-motion-install-20261110/c10429057a86/motion"
    ),
    video_editing_tasks_dir=new_tasks,
    video_editing_lease_seconds=360,
    video_editing_library_evidence_dir=Path(
        "C:/tl/acceptance/first/tasks/_library-validation"
    ),
    video_editing_native_bindings_file=Path(
        "C:/tl/dependency-binding/original-bindings.json"
    ),
    video_editing_python=sys.executable,
    video_editing_ffmpeg="C:/tl/tools/bin/ffmpeg.exe",
    video_editing_ffprobe="C:/tl/tools/bin/ffprobe.exe",
)
app = create_app(settings)
app.state.editing_dispatcher = lambda _: None
app.state.editing_planning_dispatcher = lambda _: None
factory = app.state.session_factory
old_prefix = old_tasks.as_posix().casefold() + "/"


def move_paths(value):
    if isinstance(value, dict):
        return {key: move_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [move_paths(item) for item in value]
    if isinstance(value, str) and value.replace("\\", "/").casefold().startswith(
        old_prefix
    ):
        return str(new_tasks / value.replace("\\", "/")[len(old_prefix) :])
    return value


copies = {}


def copy_checked(source, dest, digest=None):
    source, dest = Path(source), Path(dest)
    if digest is None:
        digest = sha256(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    assert sha256(source) == sha256(dest) == digest
    copies[source] = digest


with factory() as session:
    capture = session.get(EditingPlanningTaskRecord, ids["planning"])
    prepare = session.get(EditingPlanningTaskRecord, capture.prepared_task_id)
    source = session.get(EditingSourceRecord, capture.source_id)
    base_artifact = session.get(
        EditingArtifactRecord, capture.base_transcript_artifact_id
    )
    real_transcript_sha = base_artifact.sha256
    for row in (capture, prepare):
        capture_root = old_tasks / "_planning" / row.id
        for file in capture_root.rglob("*"):
            if file.is_file():
                copy_checked(file, new_tasks / file.relative_to(old_tasks))
        for artifact in row.result["artifacts"]:
            assert copies[Path(artifact["path"])] == artifact["sha256"]
        row.snapshot = move_paths(row.snapshot)
        row.result = move_paths(row.result)
    capture_hashes = {row["role"]: row["sha256"] for row in capture.result["artifacts"]}
    capture_result = capture.result
    original_source = Path(source.media_path)
    staged_source = new_tasks / "sources" / source.id / original_source.name
    copy_checked(original_source, staged_source, source.media_sha256)
    source.media_path = str(staged_source)
    base_copy = Path(move_paths(base_artifact.path))
    assert base_copy.is_relative_to(new_tasks / capture.base_task_id)
    copy_checked(base_artifact.path, base_copy, base_artifact.sha256)
    base_artifact.path = str(base_copy)
    for card in capture.snapshot["asset_cards"]:
        asset_id = card["id"]
        if not asset_id.startswith(PREFIX):
            continue
        material = session.get(EditingMaterialRecord, asset_id.removeprefix(PREFIX))
        relative = (
            Path("materials") / material.id / ("original" + SUFFIXES[material.mime])
        )
        copy_checked(old_tasks / relative, new_tasks / relative, material.sha256)
    for plan in session.scalars(
        select(EditingNativePlanRecord).where(
            EditingNativePlanRecord.base_task_id == capture.base_task_id
        )
    ):
        changed = move_paths(plan.details)
        for asset_id, asset in changed.get("asset_snapshot", {}).items():
            if asset_id == "source-" + source.id:
                assert asset["sha256"] == source.media_sha256
                asset["path"] = str(staged_source)
        plan.details = changed
    session.commit()
print(
    case,
    "staged the original model response, verified transcript and source",
    flush=True,
)
api = "/api/v1/video-studio/workspaces/" + ids["workspace"]
planning = api + "/editing-planning-tasks/" + ids["planning"]


def body(response):
    assert response.is_success, (response.status_code, response.text[:550])
    return response.json()


with TestClient(app, headers={"X-User-Id": ids["owner"]}) as client:
    candidate = body(
        client.post(planning + "/native-candidate", params={"revalidate": True})
    )
    assert (
        candidate["origin"] == "tengli_gateway"
        and candidate["continuous_preview_available"]
    ), candidate.get("warnings")
    assert (
        body(client.post(planning + "/native-candidate", params={"revalidate": True}))[
            "id"
        ]
        == candidate["id"]
    )
    count = motion_counts(row["group_id"] for row in candidate["beats"])
    assert count["distinct_groups"] >= 5
    if not args.business_capture:
        assert count == (
            {"distinct_groups": 9, "occurrences": 14}
            if case == "product"
            else {"distinct_groups": 10, "occurrences": 10}
        )
    with factory() as session:
        derived = session.get(EditingNativePlanRecord, candidate["id"])
        lineage = derived.details["planning_provenance"]
        assert lineage["artifact_sha256"] == capture_hashes
        assert content_digest(derived.semantic) == lineage["semantic_content_sha256"]
        assert (
            session.get(EditingPlanningTaskRecord, ids["planning"]).result
            == capture_result
        )
    created = body(
        client.post(
            api + "/editing-tasks",
            json={
                "source_id": candidate["source_id"],
                "request_id": str(uuid4()),
                "options": {
                    "mode": "native_plan",
                    "native_plan_id": candidate["id"],
                    "delivery": "preview_first",
                    "source_subtitles": candidate["source_subtitles"],
                    "caption_font_id": candidate["caption_font_id"],
                },
            },
        )
    )
    task = created["id"]
    endpoint = api + "/editing-tasks/" + task
    print(case, "new native task", task, count, flush=True)
    atomic_json(
        root / "submitted.json",
        {
            "task": task,
            "candidate": candidate["id"],
            "planning": ids["planning"],
            "project": ids["project"],
            "motion_counts": count,
        },
    )
    setting_names = (
        "environment",
        "auth_mode",
        "development_user_email",
        "auto_create_schema",
        "auto_process_jobs",
        "ecommerce_startup_recovery_enabled",
        "storage_backend",
        "storage_dir",
        "database_url",
        "video_editing_enabled",
        "video_editing_native_plan_enabled",
        "video_editing_planning_enabled",
        "video_script_planning_enabled",
        "video_editing_library_dir",
        "video_editing_tasks_dir",
        "video_editing_library_evidence_dir",
        "video_editing_native_bindings_file",
        "video_editing_python",
        "video_editing_ffmpeg",
        "video_editing_ffprobe",
        "video_editing_lease_seconds",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("POLARIS_")
    }
    env.update(
        {"POLARIS_" + key.upper(): str(getattr(settings, key)) for key in setting_names}
    )
    env["PYTHONUTF8"] = "1"
    with (
        (root / "worker.log").open("wb") as log,
        subprocess.Popen(
            [
                sys.executable,
                "-B",
                "backend/scripts/run_editing_worker.py",
                "--once",
                task,
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as worker,
    ):
        deadline = time.monotonic() + 750
        previous = None
        while True:
            result = body(client.get(endpoint))
            phase = (result["status"], result["stage"])
            if phase != previous:
                print(case, *phase, flush=True)
                previous = phase
            if result["status"] not in ("queued", "running"):
                break
            assert time.monotonic() < deadline and worker.poll() is None
            time.sleep(2)
        assert worker.wait(timeout=30) == 0
    assert result["status"] == "awaiting_review", result.get("error_code")
    preview = next(a for a in result["artifacts"] if a["role"] == "preview")
    assert (
        client.get(preview["url"], headers={"Range": "bytes=0-65535"}).status_code
        == 206
    )
    final = body(
        client.post(
            endpoint + "/confirm-export",
            json={
                "preview_artifact_id": preview["id"],
                "preview_sha256": preview["sha256"],
            },
        )
    )
    assert final["status"] == "completed" and final["motion_counts"] == count
    master = next(a for a in final["artifacts"] if a["role"] == "final")
    assert (
        client.get(master["url"], headers={"Range": "bytes=0-65535"}).status_code == 206
    )
    response = client.get(master["url"])
    assert response.status_code == 200
    path = root / ("website-" + case + "-verified-hd.mp4")
    path.write_bytes(response.content)
    assert sha256(path) == master["sha256"]
    subprocess.run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        check=True,
        timeout=120,
    )
    [validation] = list((new_tasks / task).rglob("validation.json"))
    attempt = validation.parent
    audit = read_json(validation)
    native = read_json(attempt / "native-plan-lineage.json")
    audio = read_json(attempt / "audio-validation.json")
    assert (
        native["base_transcript_sha256"] == real_transcript_sha
        and native["planning_origin"] == "tengli_gateway"
    )
    assert native["planning_provenance"]["artifact_sha256"] == capture_hashes
    assert (
        native["transcript_reused_exactly"]
        and native["recognition_calls"]
        == native["alignment_calls"]
        == native["planning_calls"]
        == 0
    )
    mix = audio["decoded_audio_mix"]
    assert mix["source_voice_peak_error_dbfs"] < -100 and len(audio["music"]) == 1
    assert (
        mix["selected_stems"]["fx"]["decoded_projection_gain"] > 0.9
        and mix["selected_stems"]["bgm"]["decoded_projection_gain"] > 0.9
    )
    assert len(audio["fx"]) > 0
    if not args.business_capture:
        assert len(audio["fx"]) == (16 if case == "product" else 15)
    assert sha256(source_db) == db_sha and all(
        sha256(path) == digest for path, digest in copies.items()
    )
    integrity = verify_package(settings.video_editing_library_dir)
    atomic_json(
        root / "delivery-evidence.json",
        {
            "case": case,
            "task": task,
            "planning": ids["planning"],
            "candidate": candidate["id"],
            "source_sha256": lineage["source_sha256"],
            "request_sha256": lineage["request_sha256"],
            "response_sha256": capture_hashes["response"],
            "semantic_sha256": lineage["semantic_content_sha256"],
            "transcript_sha256": real_transcript_sha,
            "provider_calls": 0,
            "original_capture_files_preserved": len(copies),
            "original_db_sha256_preserved": True,
            "duration_ms": master["duration_ms"],
            "master_dimensions": audit["master_dimensions"],
            "motion_counts": count,
            "used_groups": list(
                dict.fromkeys(
                    row["group_id"]
                    for row in candidate["beats"]
                    if row["group_id"] != "Z-M00"
                )
            ),
            "sound_cues": len(audio["fx"]),
            "music_tracks": len(audio["music"]),
            "decoded_audio_mix": mix,
            "proxy_and_master_range_status": 206,
            "download_sha256": master["sha256"],
            "full_decode": True,
            "original_library_files_verified": integrity["integrity_files"],
        },
    )
    print(
        case,
        "website-delivered full native master",
        master["duration_ms"],
        master["sha256"],
        flush=True,
    )
