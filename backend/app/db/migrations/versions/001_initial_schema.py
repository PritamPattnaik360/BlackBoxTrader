"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False, unique=True),
        sa.Column("asset_type", sa.String(10), nullable=False, server_default="stock"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "signal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("composite_score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("source_count", sa.Integer, default=0),
        sa.Column("news_score", sa.Float, nullable=True),
        sa.Column("reddit_score", sa.Float, nullable=True),
        sa.Column("raw_headlines", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_signal_ticker", "signal", ["ticker"])
    op.create_index("ix_signal_created_at", "signal", ["created_at"])

    op.create_table(
        "trade_order",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("alpaca_order_id", sa.String(50), unique=True, nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("limit_price", sa.Float, nullable=True),
        sa.Column("stop_price", sa.Float, nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="pending"),
        sa.Column("filled_qty", sa.Float, nullable=True),
        sa.Column("filled_avg_price", sa.Float, nullable=True),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("signal.id"), nullable=True),
        sa.Column("asset_class", sa.String(15), server_default="us_equity"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_trade_order_ticker", "trade_order", ["ticker"])

    op.create_table(
        "position",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("avg_entry_price", sa.Float, nullable=False),
        sa.Column("current_price", sa.Float, nullable=True),
        sa.Column("unrealized_pnl", sa.Float, nullable=True),
        sa.Column("stop_loss_price", sa.Float, nullable=True),
        sa.Column("take_profit_price", sa.Float, nullable=True),
        sa.Column("asset_class", sa.String(15), server_default="us_equity"),
        sa.Column("is_open", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_position_ticker", "position", ["ticker"])

    op.create_table(
        "portfolio_snapshot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("positions_value", sa.Float, nullable=False),
        sa.Column("day_pnl", sa.Float, nullable=False),
        sa.Column("day_pnl_pct", sa.Float, nullable=False),
        sa.Column("total_pnl", sa.Float, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_portfolio_snapshot_recorded_at", "portfolio_snapshot", ["recorded_at"])

    op.create_table(
        "ohlcv_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.UniqueConstraint("ticker", "interval", "ts"),
    )
    op.create_index("idx_ohlcv_ticker_interval_ts", "ohlcv_cache", ["ticker", "interval", "ts"])

    op.create_table(
        "backtest_run",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tickers", sa.JSON, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("initial_capital", sa.Float, server_default="100000"),
        sa.Column("strategy_name", sa.String(50), nullable=False),
        sa.Column("params", sa.JSON, nullable=True),
        sa.Column("status", sa.String(10), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "backtest_result",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_run.id"), nullable=False),
        sa.Column("total_return", sa.Float, nullable=True),
        sa.Column("cagr", sa.Float, nullable=True),
        sa.Column("sharpe", sa.Float, nullable=True),
        sa.Column("sortino", sa.Float, nullable=True),
        sa.Column("max_drawdown", sa.Float, nullable=True),
        sa.Column("calmar", sa.Float, nullable=True),
        sa.Column("win_rate", sa.Float, nullable=True),
        sa.Column("profit_factor", sa.Float, nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=True),
        sa.Column("equity_curve", sa.JSON, nullable=True),
        sa.Column("trade_log", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_result")
    op.drop_table("backtest_run")
    op.drop_table("ohlcv_cache")
    op.drop_table("portfolio_snapshot")
    op.drop_table("position")
    op.drop_table("trade_order")
    op.drop_table("signal")
    op.drop_table("watchlist")
