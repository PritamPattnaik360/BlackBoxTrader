"""Add source and quant_score to trade_order

Revision ID: 003
Revises: 002
Create Date: 2026-06-23
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trade_order", sa.Column("source",      sa.String(10), server_default="manual"))
    op.add_column("trade_order", sa.Column("quant_score", sa.Float,      nullable=True))


def downgrade() -> None:
    op.drop_column("trade_order", "quant_score")
    op.drop_column("trade_order", "source")
