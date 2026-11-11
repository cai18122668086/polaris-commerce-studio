"""Project selection memo history is separate from immutable original library."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0045"
down_revision = "20261109_0044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_library_notes",
        sa.Column("id", sa.String(40), primary_key=True),
        *[
            sa.Column(name, sa.String(40), sa.ForeignKey(target), nullable=False)
            for name, target in (
                ("workspace_id", "workspaces.id"),
                ("owner_user_id", "users.id"),
                ("project_id", "video_projects.id"),
            )
        ],
        sa.Column("library_release", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("choice", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "parent_note_id",
            sa.String(40),
            sa.ForeignKey("video_editing_library_notes.id"),
        ),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_library_note_request",
        ),
        sa.UniqueConstraint(
            "project_id",
            "owner_user_id",
            "library_release",
            "target_kind",
            "target_id",
            "sequence",
            name="uq_editing_library_note_sequence",
        ),
    )
    op.create_index(
        "ix_editing_library_note_project",
        "video_editing_library_notes",
        ["workspace_id", "owner_user_id", "project_id"],
    )


def downgrade():
    op.drop_index(
        "ix_editing_library_note_project", table_name="video_editing_library_notes"
    )
    op.drop_table("video_editing_library_notes")
