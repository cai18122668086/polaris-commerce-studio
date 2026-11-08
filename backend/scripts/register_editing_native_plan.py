"""Import one explicit operator candidate into the scoped durable plan store."""

import argparse
from pathlib import Path
from uuid import UUID

from app.config import Settings
from app.database import build_database
from app.motion_library import read_json
from app.video_editing_contracts import SemanticPlan
from app.video_editing_episode_compiler import EpisodeRecipeBundle
from app.video_editing_native_plans import register_operator_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--base-task", type=UUID, required=True)
    parser.add_argument("--request-id", type=UUID, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings(_env_file=None)
    engine, factory = build_database(settings.database_url)
    try:
        with factory() as session:
            row = register_operator_plan(
                session,
                settings,
                args.workspace,
                args.owner,
                str(args.base_task),
                str(args.request_id),
                SemanticPlan.model_validate(read_json(args.plan)),
                EpisodeRecipeBundle.model_validate(read_json(args.recipes)),
            )
            print("Registered operator candidate:", row.id, "not rendered or approved")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
