"""
Day-trade journal.

Every day trade the executor opens is recorded here, and reconcile() (run every
minute) closes the record out — same day, with entry/exit/P&L and the reason:

  take_profit — target hit (bracket leg filled, or price >= target on the fallback path)
  stop        — stop hit
  eod         — flattened before the close
  signal      — closed by a SELL signal / manual order

It also enforces "sell when in profit, same day" on the fallback path where the
broker bracket could not be placed: price at/above target or at/below stop
triggers an immediate flatten.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.day_trade import DayTrade

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


async def open_trade(ticker: str, qty: float, entry_price: float, stop_price: float | None,
                     target_price: float | None, bias: str | None, quant_score: float | None,
                     contract_symbol: str | None = None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(DayTrade(
                ticker=ticker, contract_symbol=contract_symbol, status="open", qty=qty,
                entry_price=entry_price, stop_price=stop_price, target_price=target_price,
                bias=bias, quant_score=quant_score,
            ))
            await db.commit()
        logger.info(f"[DAYTRADE] Logged OPEN {ticker} x{qty} @ {entry_price:.2f} "
                    f"stop={stop_price} target={target_price}")
    except Exception as e:
        logger.warning(f"Could not journal day trade for {ticker}: {e}")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _close(row: DayTrade, price: float, reason: str, when: datetime | None = None) -> None:
    when = when or datetime.now(timezone.utc)
    mult = 100 if row.contract_symbol else 1
    row.exit_price = price
    row.exit_time = when
    row.exit_reason = reason
    row.pnl = round((price - row.entry_price) * row.qty * mult, 2)
    row.pnl_pct = round(price / row.entry_price - 1, 4) if row.entry_price else None
    row.held_minutes = int((_aware(when) - _aware(row.entry_time)).total_seconds() // 60)
    row.status = "closed"
    logger.info(f"[DAYTRADE] Logged CLOSE {row.ticker} @ {price:.2f} pnl={row.pnl:+.2f} "
                f"({row.pnl_pct:+.2%}) held {row.held_minutes}m — {reason}")


async def reconcile() -> None:
    from app.services.trading_engine import broker, executor
    if executor.is_dry_run():
        return

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(DayTrade).where(DayTrade.status == "open"))).scalars().all()
        if not rows:
            return
        try:
            positions = await asyncio.to_thread(broker.get_positions)
        except Exception as e:
            logger.debug(f"Day-trade reconcile skipped: {e}")
            return
        held = {(p.get("contract_symbol") or p["ticker"]): p for p in positions}
        now_et = datetime.now(ET)

        for row in rows:
            symbol = row.contract_symbol or row.ticker
            pos = held.get(symbol)

            if pos is not None:
                # Still open: enforce same-day profit-taking / stop on the fallback path
                px = pos.get("current_price") or 0.0
                reason = None
                if row.target_price and px >= row.target_price:
                    reason = "take_profit"
                elif row.stop_price and px and px <= row.stop_price:
                    reason = "stop"
                if reason:
                    try:
                        await asyncio.to_thread(broker.flatten_symbol, symbol)
                        _close(row, px, reason)
                    except Exception as e:
                        logger.error(f"Day-trade flatten failed for {symbol}: {e}")
                continue

            # No longer held → find how it exited
            try:
                fill = await asyncio.to_thread(broker.get_last_sell_fill, symbol, _aware(row.entry_time))
            except Exception:
                fill = None
            if fill:
                kind = fill["type"]
                if kind == "limit":
                    reason = "take_profit"
                elif kind in ("stop", "stop_limit", "trailing_stop"):
                    reason = "stop"
                else:
                    reason = "eod" if now_et.hour == 15 and now_et.minute >= 45 else "signal"
                _close(row, fill["price"], reason, fill["filled_at"])
            else:
                _close(row, row.entry_price, "signal")   # exit fill unknown; avoid inventing P&L
        await db.commit()
