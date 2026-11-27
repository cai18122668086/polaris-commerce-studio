"""集成分支合并迁移：W2 作品条目 0055 + W6 固定形象 0059，恢复单 head。

两条迁移互不依赖，只合并分支，不做任何结构变更。
"""

revision = "20261128_m0055_0059"
down_revision = ("20261128_0055", "20261128_0059")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
