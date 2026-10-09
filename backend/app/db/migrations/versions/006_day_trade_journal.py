"""Day-trade journal table.

Revision ID: 006
Revises: 005
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_trade",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False, index=True),
        sa.Column("contract_symbol", sa.String(32), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, index=True),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("stop_price", sa.Float, nullable=True),
        sa.Column("target_price", sa.Float, nullable=True),
        sa.Column("entry_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pnl", sa.Float, nullable=True),
        sa.Column("pnl_pct", sa.Float, nullable=True),
        sa.Column("exit_reason", sa.String(15), nullable=True),
        sa.Column("bias", sa.String(8), nullable=True),
        sa.Column("quant_score", sa.Float, nullable=True),
        sa.Column("held_minutes", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("day_trade")
