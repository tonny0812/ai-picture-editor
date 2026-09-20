"""llm_configs 与 llm_config_audit

Revision ID: c3a9f1b02d47
Revises: b7d24f0a91ce
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "c3a9f1b02d47"
down_revision = "b7d24f0a91ce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_configs",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("user_id", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("planner_base_url", sa.String(length=512)),
        sa.Column("planner_api_key_enc", sa.String(length=1024)),
        sa.Column("planner_model", sa.String(length=128)),
        sa.Column("planner_timeout", sa.Integer()),
        sa.Column("planner_max_retries", sa.Integer()),
        sa.Column("images_base_url", sa.String(length=512)),
        sa.Column("images_api_key_enc", sa.String(length=1024)),
        sa.Column("images_model", sa.String(length=128)),
        sa.Column("images_sizes", sa.String(length=256)),
        sa.Column("image_provider", sa.String(length=16)),
        sa.Column("lock_image_provider", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", PgUUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    # 全局行全表最多一条；用户行每人最多一条（partial unique index）
    op.create_index(
        "uq_llm_config_global",
        "llm_configs",
        ["scope"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
    )
    op.create_index(
        "uq_llm_config_user",
        "llm_configs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'user'"),
    )
    op.create_index("ix_llm_configs_user_id", "llm_configs", ["user_id"])

    op.create_table(
        "llm_config_audit",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("target_user_id", PgUUID(as_uuid=True)),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_llm_config_audit_actor_id", "llm_config_audit", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_config_audit_actor_id", table_name="llm_config_audit")
    op.drop_table("llm_config_audit")
    op.drop_index("ix_llm_configs_user_id", table_name="llm_configs")
    op.drop_index("uq_llm_config_user", table_name="llm_configs")
    op.drop_index("uq_llm_config_global", table_name="llm_configs")
    op.drop_table("llm_configs")
