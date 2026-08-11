"""Add isolated domestic main-image runtime persistence.

Revision ID: 20260811_0007
Revises: 20260808_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0007"
down_revision: str | None = "20260808_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domestic_main_image_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("workspace_id", sa.String(40), nullable=False),
        sa.Column("created_by_user_id", sa.String(40), nullable=False),
        sa.Column("create_idempotency_key", sa.String(255), nullable=False),
        sa.Column("create_request_sha256", sa.String(64), nullable=False),
        sa.Column("technical_status", sa.String(24), nullable=False),
        sa.Column("skill_state", sa.String(48), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("session_payload", sa.JSON(), nullable=False),
        sa.Column("raw_input", sa.JSON(), nullable=False),
        sa.Column("identity_contract", sa.JSON()),
        sa.Column("plan_payload", sa.JSON()),
        sa.Column("generation_request", sa.JSON()),
        sa.Column("skill_name", sa.String(96), nullable=False),
        sa.Column("skill_version", sa.String(32), nullable=False),
        sa.Column("skill_digest", sa.String(64), nullable=False),
        sa.Column("skill_file_inventory", sa.JSON(), nullable=False),
        sa.Column("source_zip_sha256", sa.String(64), nullable=False),
        sa.Column("startup_git_commit", sa.String(40), nullable=False),
        sa.Column("image_model", sa.String(96)),
        sa.Column("image_model_version", sa.String(96)),
        sa.Column("provider_capability_status", sa.String(32), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 0", name="ck_main_image_task_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "created_by_user_id",
            "create_idempotency_key",
            name="uq_main_image_task_create_idem",
        ),
    )
    op.create_index(
        "ix_main_image_tasks_workspace_created",
        "domestic_main_image_tasks",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "domestic_main_image_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), nullable=False),
        sa.Column("asset_id", sa.String(40), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_role", sa.String(32), nullable=False),
        sa.Column("runtime_path", sa.String(1024), nullable=False),
        sa.Column("asset_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["domestic_main_image_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("task_id", "ordinal", name="uq_main_image_source_order"),
        sa.UniqueConstraint(
            "task_id", "evidence_id", name="uq_main_image_source_evidence"
        ),
    )
    op.create_table(
        "domestic_main_image_commands",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("command", sa.String(48), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("committed_revision", sa.Integer()),
        sa.Column("command_input", sa.JSON(), nullable=False),
        sa.Column("argv", sa.JSON(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=False),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("session_before_sha256", sa.String(64)),
        sa.Column("session_after_sha256", sa.String(64)),
        sa.Column("transition_committed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["domestic_main_image_tasks.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("task_id", "sequence", name="uq_main_image_command_seq"),
    )
    op.create_index(
        "ix_main_image_commands_task",
        "domestic_main_image_commands",
        ["task_id", "sequence"],
    )
    op.create_table(
        "domestic_main_image_generations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("generation_token_sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(96), nullable=False),
        sa.Column("model_version", sa.String(96), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("provider_prompt_sha256", sa.String(64)),
        sa.Column("reference_asset_ids", sa.JSON(), nullable=False),
        sa.Column("reference_roles", sa.JSON(), nullable=False),
        sa.Column("reference_order", sa.JSON(), nullable=False),
        sa.Column("edit_target", sa.JSON()),
        sa.Column("provider_idempotency_key", sa.String(255), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("request_status", sa.String(32), nullable=False),
        sa.Column("result_asset_id", sa.String(40)),
        sa.Column("cost_known", sa.Boolean(), nullable=False),
        sa.Column("cost_amount_micros", sa.BigInteger()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["domestic_main_image_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["result_asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_idempotency_key",
            name="uq_main_image_generation_provider_idem",
        ),
        sa.UniqueConstraint(
            "task_id",
            "page_index",
            "generation_token_sha256",
            "attempt",
            "operation",
            name="uq_main_image_generation_operation",
        ),
    )
    op.create_table(
        "domestic_main_image_pages",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("candidate_asset_id", sa.String(40)),
        sa.Column("accepted_asset_id", sa.String(40)),
        sa.Column("display_status", sa.String(48), nullable=False),
        sa.Column("residual_issues", sa.JSON(), nullable=False),
        sa.Column("audit_retry_count", sa.Integer(), nullable=False),
        sa.Column("candidate_saved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["domestic_main_image_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("task_id", "page_index", name="uq_main_image_task_page"),
    )


def downgrade() -> None:
    op.drop_table("domestic_main_image_pages")
    op.drop_table("domestic_main_image_generations")
    op.drop_index(
        "ix_main_image_commands_task", table_name="domestic_main_image_commands"
    )
    op.drop_table("domestic_main_image_commands")
    op.drop_table("domestic_main_image_sources")
    op.drop_index(
        "ix_main_image_tasks_workspace_created", table_name="domestic_main_image_tasks"
    )
    op.drop_table("domestic_main_image_tasks")
