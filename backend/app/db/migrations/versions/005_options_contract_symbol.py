"""Add contract_symbol to trade_order and position for options trading.

Revision ID: 005
Revises: 004
Create Date: 2026-08-29
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trade_order", sa.Column("contract_symbol", sa.String(32), nullable=True))
    op.add_column("position",    sa.Column("contract_symbol", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("position",    "contract_symbol")
    op.drop_column("trade_order", "contract_symbol")
