"""
End-of-day flatten for day trades.

Positions opened with source="daytrade" are never meant to be held overnight.
Shortly before the close this cancels their stop / take-profit legs and
liquidates whatever is still open.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.trade import TradeOrder
from app.services.trading_engine import broker, executor

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


async def run_day_trade_flatten():
    if executor.is_dry_run():
        return

    # submitted_at is stored as naive UTC; compare against today's ET midnight in UTC
    midnight_et = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = midnight_et.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(TradeOrder).where(
                TradeOrder.source == "daytrade",
                TradeOrder.side == "buy",
                TradeOrder.submitted_at >= cutoff,
            )
        )).scalars().all()
    day_tickers = {r.ticker for r in rows}
    if not day_tickers:
        return

    try:
        positions = await asyncio.to_thread(broker.get_positions)
    except Exception as e:
        logger.error(f"Day-trade flatten: could not fetch positions: {e}")
        return

    for pos in positions:
        if pos["ticker"] not in day_tickers:
            continue
        symbol = pos.get("contract_symbol") or pos["ticker"]
        try:
            await asyncio.to_thread(broker.flatten_symbol, symbol)
            logger.info(f"[DAYTRADE] EOD flatten: closed {symbol} (qty {pos['qty']})")
            await executor._save_order(
                ticker=pos["ticker"], side="sell", qty=abs(pos["qty"]),
                price=pos.get("current_price") or 0.0, stop_price=None, signal_id=None,
                source="daytrade", quant_score=None,
                asset_class="us_option" if pos.get("contract_symbol") else "us_equity",
                contract_symbol=pos.get("contract_symbol"),
            )
        except Exception as e:
            logger.error(f"Day-trade flatten failed for {symbol}: {e}")

    from app.services.trading_engine import day_journal
    await day_journal.reconcile()
