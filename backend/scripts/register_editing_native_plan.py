"""Bind trusted recipes to an operator candidate or captured server planning job."""

import argparse
from pathlib import Path
from uuid import UUID

from app.config import Settings
from app.database import build_database
from app.motion_library import read_json
from app.video_editing_contracts import SemanticPlan
from app.video_editing_episode_compiler import EpisodeRecipeBundle
from app.video_editing_native_plans import register_gateway_plan, register_operator_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--base-task", type=UUID)
    parser.add_argument("--request-id", type=UUID, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--planning-task", type=UUID)
    parser.add_argument("--recipes", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.base_task) != bool(args.plan):
        parser.error(
            "--base-task is required only with --plan; server jobs own their base task"
        )
    settings = Settings(_env_file=None)
    engine, factory = build_database(settings.database_url)
    try:
        with factory() as session:
            recipes = EpisodeRecipeBundle.model_validate(read_json(args.recipes))
            if args.planning_task:
                row = register_gateway_plan(
                    session,
                    settings,
                    args.workspace,
                    args.owner,
                    str(args.planning_task),
                    str(args.request_id),
                    recipes,
                )
            else:
                row = register_operator_plan(
                    session,
                    settings,
                    args.workspace,
                    args.owner,
                    str(args.base_task),
                    str(args.request_id),
                    SemanticPlan.model_validate(read_json(args.plan)),
                    recipes,
                )
            print(
                "Registered native candidate:",
                row.id,
                row.origin,
                "not rendered or approved",
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
