"""
Trade executor.

Two runtime modes:
  dry_run=True  (default) — decisions are logged but NO Alpaca API calls made
  dry_run=False           — orders are submitted to Alpaca (paper or live)

  autonomous=True — the scheduler is allowed to auto-submit orders
  autonomous=False — system only generates signals; user trades manually

Enabling autonomous mode automatically disables dry_run (enables paper execution).
"""
import logging
from app.config import settings
from app.services.nlp_engine.aggregator import CompositeSignal
from app.services.risk_manager import position_sizer, portfolio_limits, stop_loss
from app.services.market_data.yfinance_client import get_snapshot
from app.services.adaptive.adaptive_engine import get_param

logger = logging.getLogger(__name__)

_dry_run:    bool = True   # always start safe
_autonomous: bool = False  # must be explicitly enabled


# ── Mode controls ─────────────────────────────────────────────────────────────

def enable_autonomous() -> None:
    global _autonomous, _dry_run
    _autonomous = True
    _dry_run    = False   # autonomous requires real execution
    logger.info("Autonomous trading ENABLED (paper execution active)")


def disable_autonomous() -> None:
    global _autonomous, _dry_run
    _autonomous = False
    _dry_run    = True
    logger.info("Autonomous trading disabled (dry-run restored)")


def enable_live_execution() -> None:
    global _dry_run
    _dry_run = False
    logger.info("Live execution ENABLED")


def disable_live_execution() -> None:
    global _dry_run
    _dry_run = True
    logger.info("Live execution disabled (dry-run mode)")


def is_dry_run()    -> bool: return _dry_run
def is_autonomous() -> bool: return _autonomous


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_signal(
    signal:             CompositeSignal,
    open_position_count: int,
    equity:             float,
    source:             str = "auto",
    quant_score:        float | None = None,
) -> dict:
    """
    Evaluate a signal through the risk gate and submit an order if approved.

    Args:
        signal:              NLP CompositeSignal (direction, ticker, scores).
        open_position_count: Current number of open positions.
        equity:              Current portfolio equity.
        source:              "auto" | "manual".
        quant_score:         Combined quant score (stored on the order for reference).
    """
    result = {"ticker": signal.ticker, "direction": signal.direction, "action": None, "reason": None}

    if signal.direction == "HOLD":
        result.update(action="skip", reason="HOLD signal")
        return result

    # ── Risk gate ─────────────────────────────────────────────────────────────
    if portfolio_limits.is_halted(equity):
        result.update(action="skip", reason="Portfolio halted (daily loss or max drawdown)")
        return result

    if not portfolio_limits.check_position_count(open_position_count):
        result.update(action="skip", reason=f"Max open positions ({settings.max_open_positions}) reached")
        return result

    snapshot = get_snapshot(signal.ticker)
    price    = snapshot.get("price")
    if not price or price <= 0:
        result.update(action="skip", reason="Could not fetch current price — yfinance returned None")
        logger.warning(f"Price fetch failed for {signal.ticker} — snapshot={snapshot}")
        return result

    side = "buy" if signal.direction == "BUY" else "sell"

    # ── Position guard ────────────────────────────────────────────────────────
    # Fetch live positions once (cheap Alpaca call) so we never short-sell
    # on a paper account and never double-buy a ticker we already hold.
    try:
        from app.services.trading_engine import broker
        live_positions = {p["ticker"] for p in broker.get_positions()}
    except Exception as e:
        logger.warning(f"Could not fetch positions for guard check: {e} — proceeding")
        live_positions = set()

    if side == "buy" and signal.ticker in live_positions:
        result.update(action="skip", reason="Already holding position — skipping duplicate BUY")
        return result

    if side == "sell" and signal.ticker not in live_positions:
        result.update(action="skip", reason="No position to sell — skipping SELL (no short-selling)")
        return result

    atr      = stop_loss.calculate_atr(signal.ticker)
    risk_pct = get_param("risk_per_trade_pct")
    qty = position_sizer.atr_based_size(equity, price, atr, risk_pct=risk_pct) if atr > 0 \
        else position_sizer.fixed_fraction_size(equity, price, risk_pct=risk_pct)
    qty = position_sizer.clamp_to_max(qty, price, equity)

    if qty <= 0:
        result.update(action="skip", reason="Position sizer returned 0 shares")
        return result

    notional = qty * price
    if not portfolio_limits.check_position_size(notional, equity):
        result.update(action="skip",
                      reason=f"Position ${notional:.0f} exceeds max {settings.max_position_pct:.0%} of equity")
        return result

    if _dry_run:
        logger.info(
            f"[DRY RUN] Would {side.upper()} {qty}×{signal.ticker} "
            f"@~${price:.2f} (quant={quant_score})"
        )
        result.update(action="dry_run", qty=qty, price=price,
                      stop=stop_loss.atr_stop_price(price, atr, side))
        return result

    # ── Submit to Alpaca ──────────────────────────────────────────────────────
    try:
        from app.services.trading_engine import broker
        order = broker.submit_market_order(signal.ticker, side, qty)
        logger.info(f"[{source.upper()}] Order submitted: {order}")

        stop_price = stop_loss.atr_stop_price(price, atr, side)
        stop_side  = "sell" if side == "buy" else "buy"
        broker.submit_stop_order(signal.ticker, stop_side, qty, stop_price)

        # Persist order with source tag
        await _save_order(
            ticker=signal.ticker, side=side, qty=qty, price=price,
            stop_price=stop_price, signal_id=None, source=source,
            quant_score=quant_score,
        )

        result.update(action="submitted", order=str(order), stop_price=stop_price)
    except Exception as e:
        logger.error(f"Order submission failed for {signal.ticker}: {e}")
        result.update(action="error", reason=str(e))

    return result


async def _save_order(ticker, side, qty, price, stop_price, signal_id, source, quant_score):
    """Persist the order record to DB."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.trade import TradeOrder
        async with AsyncSessionLocal() as db:
            db.add(TradeOrder(
                ticker=ticker, side=side, order_type="market",
                qty=qty, filled_avg_price=price,
                stop_price=stop_price, signal_id=signal_id,
                status="submitted", source=source,
                quant_score=quant_score,
            ))
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not persist order record: {e}")
