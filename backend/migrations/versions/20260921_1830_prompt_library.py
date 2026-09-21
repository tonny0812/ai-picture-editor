"""提示词库、模板与多轮轮次

Revision ID: f736011e6f77
Revises: c3a9f1b02d47
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f736011e6f77"
down_revision = "c3a9f1b02d47"
branch_labels = None
depends_on = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "prompt_entries",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("ratio", sa.String(length=8), nullable=False, server_default="1:1"),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("preview_asset_id", _uuid(), nullable=True),
        sa.Column("source_run_id", _uuid(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["preview_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_run_id"], ["tool_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_entries_category", "prompt_entries", ["category"])
    op.create_index("ix_prompt_entries_user_id", "prompt_entries", ["user_id"])
    op.alter_column("prompt_entries", "ratio", server_default=None)
    op.alter_column("prompt_entries", "category", server_default=None)
    op.alter_column("prompt_entries", "tags", server_default=None)
    op.alter_column("prompt_entries", "use_count", server_default=None)

    op.create_table(
        "prompt_templates",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # NULL 表示内置模板：所有人可见，写操作由服务层拒绝
        sa.Column("user_id", _uuid(), nullable=True),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("negative_template", sa.Text(), nullable=True),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("default_ratio", sa.String(length=8), nullable=False, server_default="1:1"),
        sa.Column("default_count", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("preview_asset_id", _uuid(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["preview_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_templates_category", "prompt_templates", ["category"])
    op.create_index("ix_prompt_templates_user_id", "prompt_templates", ["user_id"])
    op.alter_column("prompt_templates", "category", server_default=None)
    op.alter_column("prompt_templates", "variables", server_default=None)
    op.alter_column("prompt_templates", "default_ratio", server_default=None)
    op.alter_column("prompt_templates", "default_count", server_default=None)
    op.alter_column("prompt_templates", "use_count", server_default=None)

    op.add_column("tool_runs", sa.Column("parent_run_id", _uuid(), nullable=True))
    op.add_column("tool_runs", sa.Column("round", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tool_runs", sa.Column("round_note", sa.Text(), nullable=True))
    op.create_index("ix_tool_runs_parent_run_id", "tool_runs", ["parent_run_id"])
    op.create_foreign_key(
        "fk_tool_runs_parent_run_id", "tool_runs", "tool_runs", ["parent_run_id"], ["id"], ondelete="SET NULL"
    )
    op.alter_column("tool_runs", "round", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_tool_runs_parent_run_id", "tool_runs", type_="foreignkey")
    op.drop_index("ix_tool_runs_parent_run_id", table_name="tool_runs")
    op.drop_column("tool_runs", "round_note")
    op.drop_column("tool_runs", "round")
    op.drop_column("tool_runs", "parent_run_id")
    op.drop_table("prompt_templates")
    op.drop_table("prompt_entries")
