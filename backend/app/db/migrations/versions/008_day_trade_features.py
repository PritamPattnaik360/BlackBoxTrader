"""Add entry-condition snapshot (features) to day_trade for pattern learning.

Revision ID: 008
Revises: 007
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("day_trade", sa.Column("features", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("day_trade", "features")
