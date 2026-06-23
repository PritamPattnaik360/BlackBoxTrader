"""Add advisor and LLM training tables.

Revision ID: 004
Revises: 003
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_training_sample",
        sa.Column("id",          sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instruction", sa.Text(),    nullable=False),
        sa.Column("response",    sa.Text(),    nullable=False),
        sa.Column("ticker",      sa.String(16), nullable=True),
        sa.Column("quality",     sa.Float(),   nullable=False, server_default="0.5"),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("pnl_pct",     sa.Float(),   nullable=True),
        sa.Column("source",      sa.String(32), nullable=False, server_default="trade_outcome"),
        sa.Column("metadata",    sa.JSON(),    nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "advisor_conversation",
        sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("role",       sa.String(16), nullable=False),
        sa.Column("content",    sa.Text(),    nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("advisor_conversation")
    op.drop_table("llm_training_sample")
