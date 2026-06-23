"""Adaptive learning tables

Revision ID: 002
Revises: 001
Create Date: 2026-06-23
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_outcome",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("signal_id", sa.Integer, nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("signal_direction", sa.String(5), nullable=False),
        sa.Column("composite_score", sa.Float, nullable=False),
        sa.Column("news_score", sa.Float, nullable=True),
        sa.Column("reddit_score", sa.Float, nullable=True),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=False),
        sa.Column("pnl_pct", sa.Float, nullable=False),
        sa.Column("was_correct", sa.Boolean, nullable=False),
        sa.Column("regime_at_entry", sa.String(20), server_default="normal"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_signal_outcome_ticker", "signal_outcome", ["ticker"])
    op.create_index("ix_signal_outcome_created_at", "signal_outcome", ["created_at"])

    op.create_table(
        "adaptive_param",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("previous_value", sa.Float, nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_adaptive_param_name", "adaptive_param", ["name"])
    op.create_index("ix_adaptive_param_generation", "adaptive_param", ["generation"])

    op.create_table(
        "adaptive_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("data", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_adaptive_event_created_at", "adaptive_event", ["created_at"])


def downgrade() -> None:
    op.drop_table("adaptive_event")
    op.drop_table("adaptive_param")
    op.drop_table("signal_outcome")
