"""Add explicit inspiration workflow routing configuration."""

import sqlalchemy as sa
from alembic import op

revision = "20260828_0013"
down_revision = "20260824_0012"
branch_labels = None
depends_on = None

PRODUCT_PROMPT_CASE_TITLES = (
    "生成AI模特",
    "衣服上身（无中生有）",
    "卖点图（多姿势展示）",
    "衣服上身（模特无中生有）",
    "改造型",
)


def upgrade() -> None:
    op.add_column(
        "inspiration_cases",
        sa.Column(
            "workflow_type",
            sa.String(24),
            nullable=False,
            server_default="legacy_unclassified",
        ),
    )
    op.add_column(
        "inspiration_cases",
        sa.Column(
            "reference_source",
            sa.String(20),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "inspiration_cases",
        sa.Column(
            "configuration_status",
            sa.String(16),
            nullable=False,
            server_default="incomplete",
        ),
    )
    op.add_column(
        "inspiration_cases",
        sa.Column(
            "button_label",
            sa.String(80),
            nullable=False,
            server_default="一键做同款",
        ),
    )
    op.create_check_constraint(
        "ck_inspiration_cases_workflow_type",
        "inspiration_cases",
        "workflow_type IN ('reference_remix', 'product_prompt', 'local_edit', 'legacy_unclassified')",
    )
    op.create_check_constraint(
        "ck_inspiration_cases_reference_source",
        "inspiration_cases",
        "reference_source IN ('admin_reference', 'result_image', 'none')",
    )
    op.create_check_constraint(
        "ck_inspiration_cases_configuration_status",
        "inspiration_cases",
        "configuration_status IN ('draft', 'ready', 'incomplete', 'archived')",
    )
    # These five cases are explicitly confirmed for the product-prompt path.
    # All other historical cases remain fail-closed and require admin
    # configuration instead of being silently treated as reference remixes.
    op.execute(
        sa.text(
            "UPDATE inspiration_cases SET workflow_type = 'product_prompt', "
            "reference_source = 'none', "
            "configuration_status = CASE WHEN trim(prompt) <> '' THEN 'ready' ELSE 'incomplete' END "
            "WHERE title IN ("
            + ", ".join(f"'{title}'" for title in PRODUCT_PROMPT_CASE_TITLES)
            + ")"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_inspiration_cases_configuration_status",
        "inspiration_cases",
        type_="check",
    )
    op.drop_constraint(
        "ck_inspiration_cases_reference_source",
        "inspiration_cases",
        type_="check",
    )
    op.drop_constraint(
        "ck_inspiration_cases_workflow_type",
        "inspiration_cases",
        type_="check",
    )
    op.drop_column("inspiration_cases", "button_label")
    op.drop_column("inspiration_cases", "configuration_status")
    op.drop_column("inspiration_cases", "reference_source")
    op.drop_column("inspiration_cases", "workflow_type")
