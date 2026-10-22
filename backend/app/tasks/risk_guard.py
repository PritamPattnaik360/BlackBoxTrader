"""
Risk guard — runs every settings.risk_guard_interval seconds.

1. Feeds equity + SPY's daily move into the circuit breaker (portfolio_limits).
2. While the breaker is tripped and flatten_on_halt is on, liquidates everything.
3. Hard per-position stop: closes any single position down more than
   position_max_loss_pct (option_max_loss_pct for options) — a backstop for
   positions whose broker-side stop is missing, gapped through, or never existed
   (options carry no stop order at all).

Orders are only sent when execution is live and the market is open; in dry-run
it just logs what it would do.
"""
import asyncio
import logging

from app.config import settings
from app.services.risk_manager import portfolio_limits
from app.services.trading_engine import broker, executor

logger = logging.getLogger(__name__)


def _spy_change_pct() -> float | None:
    """SPY's move vs. the prior close, e.g. -0.034 for -3.4%."""
    try:
        import yfinance as yf
        info = yf.Ticker("SPY").fast_info
        last, prev = info.last_price, info.previous_close
        if last and prev:
            return (last - prev) / prev
    except Exception as e:
        logger.debug(f"Risk guard: SPY quote unavailable: {e}")
    return None


async def _close(pos: dict, why: str) -> None:
    symbol = pos.get("contract_symbol") or pos["ticker"]
    if executor.is_dry_run():
        logger.warning(f"[RISK][DRY RUN] Would close {symbol}: {why}")
        return
    try:
        await asyncio.to_thread(broker.flatten_symbol, symbol)
        logger.warning(f"[RISK] Closed {symbol} (qty {pos['qty']}): {why}")
        await executor._save_order(
            ticker=pos["ticker"], side="sell", qty=abs(pos["qty"]),
            price=pos.get("current_price") or 0.0, stop_price=None, signal_id=None,
            source="risk_stop", quant_score=None,
            asset_class="us_option" if pos.get("contract_symbol") else "us_equity",
            contract_symbol=pos.get("contract_symbol"),
        )
    except Exception as e:
        logger.error(f"[RISK] Failed to close {symbol}: {e}")


async def run_risk_guard():
    try:
        account = await asyncio.to_thread(broker.get_account)
        positions = await asyncio.to_thread(broker.get_positions)
        market_open = await asyncio.to_thread(broker.is_market_open)
    except Exception as e:
        logger.debug(f"Risk guard skipped (broker unavailable): {e}")
        return

    equity = account["equity"]
    portfolio_limits.update_equity(equity, account.get("last_equity"))
    spy = await asyncio.to_thread(_spy_change_pct) if market_open else None
    halted = portfolio_limits.evaluate(equity, spy)

    if not market_open or not positions:
        return

    if halted and settings.flatten_on_halt:
        reason = portfolio_limits.status()["reason"]
        if executor.is_dry_run():
            logger.warning(f"[RISK][DRY RUN] Breaker tripped ({reason}) — would liquidate {len(positions)} positions")
            return
        logger.critical(f"[RISK] Breaker tripped ({reason}) — liquidating {len(positions)} positions")
        try:
            await asyncio.to_thread(broker.flatten_all)
        except Exception as e:
            logger.error(f"[RISK] flatten_all failed ({e}) — closing one by one")
            for pos in positions:
                await _close(pos, f"circuit breaker: {reason}")
        await _after_exits()
        return

    closed = False
    for pos in positions:
        limit = settings.option_max_loss_pct if pos.get("contract_symbol") else settings.position_max_loss_pct
        loss = pos.get("unrealized_pnl_pct") or 0.0
        if loss <= -limit:
            await _close(pos, f"hard stop: {loss:.1%} <= -{limit:.0%}")
            closed = True
    if closed:
        await _after_exits()


async def _after_exits():
    from app.services.trading_engine import day_journal
    try:
        await day_journal.reconcile()
    except Exception as e:
        logger.debug(f"Risk guard: journal reconcile failed: {e}")
