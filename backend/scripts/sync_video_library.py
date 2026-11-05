"""Sync provider-public video models into the local catalogue without paid copies."""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy.engine import make_url  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Base, build_database  # noqa: E402
from app.video_generation import OWNED_IMAGE  # noqa: E402
from app.video_generation_models import VideoAvatarRecord  # noqa: E402
from app.video_providers import VideoProviders, safe_media_url  # noqa: E402


def main():
    settings = Settings(_env_file=BACKEND / ".env")
    if settings.environment == "production":
        raise SystemExit("This helper is for local development; no production writes.")
    url = make_url(settings.database_url)
    if (
        url.drivername.startswith("sqlite")
        and url.database
        and not Path(url.database).is_absolute()
    ):
        url = url.set(database=str((BACKEND / url.database).resolve()))
    engine, factory = build_database(str(url))
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    provider = VideoProviders(settings)
    models = provider.models()
    count = 0
    with factory() as session:
        for model in models:
            if (
                not model.get("is_public")
                or not model.get("is_active", True)
                or model.get("model_type") != "video"
            ):
                continue
            id = "qy-model-" + str(model["id"])
            row = session.get(VideoAvatarRecord, id) or VideoAvatarRecord(
                id=id, source="quanyu_public"
            )
            row.name = model["model_name"]
            row.video_url = safe_media_url(model["video_url"])
            row.provider_model_id = model["id"]
            row.active = True
            name = model["model_name"].split("-")[0]
            session.commit()
            try:
                matches = provider.request(
                    "quanyu",
                    "GET",
                    "/api/digital_human/public-library",
                    params={"q": name, "limit": 100},
                ).get("items", [])
                genders = {
                    m.get("gender")
                    for m in matches
                    if m.get("name", "").split("-")[0] == name
                    and m.get("gender") in {"female", "male"}
                }
                if len(genders) == 1:
                    row.gender = "女" if "female" in genders else "男"
            except Exception:
                pass
            session.add(row)
            count += 1
        manifest = settings.video_media_dir / "self-owned" / "registered-template.json"
        data = (
            json.loads(manifest.read_text(encoding="utf-8"))
            if manifest.exists()
            else {}
        )
        if data.get("model_id") and not data.get("rejected_reason"):
            row = session.get(
                VideoAvatarRecord, "self-presenter-female-v1"
            ) or VideoAvatarRecord(id="self-presenter-female-v1", source="self_owned")
            row.name, row.gender = "清禾·原创形象", "女"
            row.cover_path = str(OWNED_IMAGE)
            row.provider_model_id = int(data["model_id"])
            row.video_url = safe_media_url(data["video_url"])
            session.add(row)
        session.commit()
    print(
        f"Synced {count} provider-public models; "
        "private provider models excluded; no paid import calls."
    )


if __name__ == "__main__":
    main()
