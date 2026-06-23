import logging
from app.db.session import AsyncSessionLocal
from app.models.position import Position
from app.models.portfolio import PortfolioSnapshot
from app.services.risk_manager import portfolio_limits
from sqlalchemy import update, select

logger = logging.getLogger(__name__)


async def run_portfolio_sync():
    try:
        from app.services.trading_engine.broker import get_account, get_positions
        account  = get_account()
        positions = get_positions()
        portfolio_limits.update_equity(account["equity"])
    except Exception as e:
        logger.debug(f"Portfolio sync skipped (broker unavailable): {e}")
        return

    async with AsyncSessionLocal() as db:
        # ── Save currently open positions BEFORE wiping ──────────────────────
        result = await db.execute(select(Position).where(Position.is_open == True))
        prev_open: dict[str, Position] = {p.ticker: p for p in result.scalars().all()}

        # ── Wipe and re-sync from broker ─────────────────────────────────────
        await db.execute(update(Position).where(Position.is_open == True).values(is_open=False))

        new_tickers: set[str] = set()
        for p in positions:
            db.add(Position(
                ticker=p["ticker"],
                qty=p["qty"],
                avg_entry_price=p["avg_entry_price"],
                current_price=p["current_price"],
                unrealized_pnl=p["unrealized_pnl"],
                asset_class=p.get("asset_class", "us_equity"),
                is_open=True,
            ))
            new_tickers.add(p["ticker"])

        await db.commit()

    # ── Record outcomes for tickers that just closed ─────────────────────────
    closed_tickers = set(prev_open.keys()) - new_tickers
    if not closed_tickers:
        return

    from app.models.signal import Signal
    from app.services.adaptive.performance_tracker import record_outcome
    from app.services.adaptive.adaptive_engine import get_regime

    async with AsyncSessionLocal() as db2:
        for ticker in closed_tickers:
            prev = prev_open[ticker]
            # Use last-known current_price as exit price proxy
            exit_price = prev.current_price or prev.avg_entry_price
            if not exit_price:
                continue

            # Find the most recent non-HOLD signal for this ticker
            sig_result = await db2.execute(
                select(Signal)
                .where(Signal.ticker == ticker, Signal.direction != "HOLD")
                .order_by(Signal.created_at.desc())
                .limit(1)
            )
            last_signal = sig_result.scalar_one_or_none()
            if last_signal is None:
                continue

            await record_outcome(
                signal_id=last_signal.id,
                ticker=ticker,
                signal_direction=last_signal.direction,
                composite_score=last_signal.composite_score,
                news_score=last_signal.news_score,
                reddit_score=last_signal.reddit_score,
                entry_price=float(prev.avg_entry_price),
                exit_price=float(exit_price),
                regime=get_regime(),
            )
