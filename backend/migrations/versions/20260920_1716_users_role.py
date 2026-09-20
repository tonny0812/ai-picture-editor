"""users role

Revision ID: b7d24f0a91ce
Revises: fa850313b768
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d24f0a91ce"
down_revision = "fa850313b768"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 存量用户一律按普通用户处理，默认值仅用于回填，之后交给 ORM 的 default
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
    )
    op.alter_column("users", "role", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "role")
