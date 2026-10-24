"""
Trade executor.

Two runtime modes:
  dry_run=True  (default) — decisions are logged but NO Alpaca API calls made
  dry_run=False           — orders are submitted to Alpaca (paper or live)

  autonomous=True — the scheduler is allowed to auto-submit orders
  autonomous=False — system only generates signals; user trades manually

Enabling autonomous mode automatically disables dry_run (enables paper execution).

When settings.enable_options_trading is on, signals trade long options
instead of shares (see _execute_options_signal): BUY opens a call, SELL
opens a put (options mode never shorts shares).

Short day trades (settings.enable_short_day_trades): with options trading off and the
market bias "bear", a strong intraday breakdown (style="short", direction SELL, no
position held) opens a SHORT with a bracket order — stop above, take-profit below —
that is covered by 15:50 ET. A BUY signal on a short position covers it.

Exits (SELL on a long / BUY on a short) always close the WHOLE position: open stop and
bracket orders on the symbol are cancelled first, then it is liquidated at market. No
protective stop is attached to an exit.
"""
import asyncio
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from app.config import settings
from app.services.nlp_engine.aggregator import CompositeSignal
from app.services.risk_manager import position_sizer, portfolio_limits, stop_loss
from app.services.market_data.yfinance_client import get_snapshot
from app.services.adaptive.adaptive_engine import get_param

logger = logging.getLogger(__name__)

_dry_run:    bool = True   # always start safe
_autonomous: bool = False  # must be explicitly enabled

DAY_STOP_ATR    = 0.6   # day-trade stop distance in daily ATRs
DAY_REWARD_RISK = 2.0   # day-trade take-profit as a multiple of the stop distance


def _pdt_allows_day_trade(equity: float) -> bool:
    """US pattern-day-trader rule: under $25k equity, max 3 day trades per 5 days."""
    if equity >= 25_000:
        return True
    try:
        from app.services.trading_engine import broker
        return broker.get_account().get("day_trade_count", 0) < 3
    except Exception:
        return True   # can't check (e.g. no keys); the broker enforces it anyway


def _day_entry_block_reason(quant_score: float | None, now_et: datetime,
                            vwap_score: float | None = None) -> str | None:
    """Hard gates on opening a day trade (score floor + VWAP confirmation + entry cutoff). None = allowed."""
    if quant_score is None or quant_score < settings.day_trade_min_score:
        return f"Day-trade score {quant_score} below hard floor {settings.day_trade_min_score}"
    if vwap_score is None or vwap_score < settings.day_trade_min_vwap:
        return f"VWAP score {vwap_score} below {settings.day_trade_min_vwap} — price not far enough above VWAP"
    cutoff = dtime.fromisoformat(settings.day_trade_entry_cutoff)
    if now_et.time() > cutoff:
        return f"Past day-trade entry cutoff ({settings.day_trade_entry_cutoff} ET)"
    return None


def _short_entry_block_reason(quant_score: float | None, now_et: datetime,
                              vwap_score: float | None = None) -> str | None:
    """Mirror of _day_entry_block_reason for SHORT day trades: a strong NEGATIVE score and price
    well BELOW session VWAP, before the entry cutoff. None = allowed."""
    if not settings.enable_short_day_trades:
        return "Short day trades are disabled (ENABLE_SHORT_DAY_TRADES=false)"
    if settings.trading_mode == "live" and not settings.allow_short_live:
        return "Short selling in LIVE mode needs ALLOW_SHORT_LIVE=true"
    if quant_score is None or quant_score > -settings.day_trade_min_score:
        return f"Short score {quant_score} not below -{settings.day_trade_min_score}"
    if vwap_score is None or vwap_score > -settings.day_trade_min_vwap:
        return f"VWAP score {vwap_score} not below -{settings.day_trade_min_vwap} — price not far enough below VWAP"
    cutoff = dtime.fromisoformat(settings.day_trade_entry_cutoff)
    if now_et.time() > cutoff:
        return f"Past day-trade entry cutoff ({settings.day_trade_entry_cutoff} ET)"
    return None


def _shortable_block_reason(ticker: str) -> str | None:
    """Alpaca must allow shorting the account and the stock must be shortable and easy to borrow."""
    try:
        from app.services.trading_engine import broker
        if not broker.get_account().get("shorting_enabled", False):
            return "Account is not enabled for short selling"
        flags = broker.get_asset_flags(ticker)
        if not flags["tradable"]:
            return f"{ticker} is not tradable"
        if not flags["shortable"]:
            return f"{ticker} is not shortable"
        if not flags["easy_to_borrow"]:
            return f"{ticker} is hard to borrow"
    except Exception as e:
        return f"Could not verify shortability for {ticker}: {e}"
    return None


def _closes_position(direction: str, held: dict | None) -> bool:
    """True when this signal would reduce exposure (sell a long / cover a short / close an opposite option)."""
    if held is None:
        return False
    if held.get("option_type") is None:
        if held.get("qty", 0) < 0:
            return direction == "BUY"      # covering a short
        return direction == "SELL"
    return held["option_type"] != ("call" if direction == "BUY" else "put")


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
    style:              str = "swing",
    size_mult:          float = 1.0,
    stop_mult_adj:      float = 0.0,
    bias:               str | None = None,
    vwap_score:         float | None = None,
) -> dict:
    """
    Evaluate a signal through the risk gate and submit an order if approved.

    Args:
        signal:              NLP CompositeSignal (direction, ticker, scores).
        open_position_count: Current number of open positions.
        equity:              Current portfolio equity.
        source:              "auto" | "manual".
        quant_score:         Combined quant score (stored on the order for reference).
        style:               "swing" (hold, ATR stop) or "day" (tight stop + take-profit
                             bracket, flattened before the close).
        size_mult:           Market-bias position-size multiplier (bear = 0.5).
        stop_mult_adj:       Market-bias adjustment to the ATR stop multiplier.
        vwap_score:          Intraday VWAP component; day-trade entries need it above
                             settings.day_trade_min_vwap.
    """
    result = {"ticker": signal.ticker, "direction": signal.direction, "action": None, "reason": None}

    if signal.direction == "HOLD":
        result.update(action="skip", reason="HOLD signal")
        return result

    is_day   = style == "day" and signal.direction == "BUY"
    is_short = style == "short" and signal.direction == "SELL"
    if is_day or is_short:
        source = "daytrade"

    # ── Risk gate ─────────────────────────────────────────────────────────────
    halted = portfolio_limits.is_halted(equity)

    if not portfolio_limits.check_position_count(open_position_count):
        result.update(action="skip", reason=f"Max open positions ({settings.max_open_positions}) reached")
        return result

    snapshot = get_snapshot(signal.ticker)
    price    = snapshot.get("price")
    if not price or price <= 0:
        result.update(action="skip", reason="Could not fetch current price — yfinance returned None")
        logger.warning(f"Price fetch failed for {signal.ticker} — snapshot={snapshot}")
        return result

    # ── Position guard ────────────────────────────────────────────────────────
    # Fetch live positions once (cheap Alpaca call) so we never short-sell
    # on a paper account and never double-buy a ticker we already hold.
    # broker.get_positions() normalizes options contracts back to their
    # underlying ticker, so this lookup works the same for both asset classes.
    try:
        from app.services.trading_engine import broker
        live_positions = broker.get_positions()
    except Exception as e:
        logger.warning(f"Could not fetch positions for guard check: {e} — proceeding")
        live_positions = []
    held = next((p for p in live_positions if p["ticker"] == signal.ticker), None)

    # A tripped circuit breaker blocks new entries but must never block an exit
    if halted and not _closes_position(signal.direction, held):
        reason = portfolio_limits.status()["reason"]
        result.update(action="skip", reason=f"Circuit breaker tripped ({reason}) — no new entries")
        return result

    covering_short = (held is not None and held.get("option_type") is None
                      and held.get("qty", 0) < 0 and signal.direction == "BUY")

    # Day-trade-only: no overnight/swing ENTRIES (covering a short is an exit, always allowed)
    if (settings.day_trade_only and signal.direction == "BUY" and not is_day and not covering_short):
        result.update(action="skip", reason="Day-trade-only mode: no qualifying intraday setup (no overnight/swing entries)")
        return result

    if is_day and held is None:
        block = _day_entry_block_reason(quant_score, datetime.now(ZoneInfo("America/New_York")), vwap_score)
        if block:
            result.update(action="skip", reason=block)
            return result

    if is_short and held is None and not settings.enable_options_trading:
        block = _short_entry_block_reason(quant_score, datetime.now(ZoneInfo("America/New_York")), vwap_score)
        if block:
            result.update(action="skip", reason=block)
            return result

    if (is_day or is_short) and held is None and not _pdt_allows_day_trade(equity):
        result.update(action="skip", reason="Pattern-day-trader limit: 3 day trades used and equity < $25k")
        return result

    if settings.enable_options_trading:
        return await _execute_options_signal(signal, price, equity, held, source, quant_score, size_mult)

    side = "buy" if signal.direction == "BUY" else "sell"

    # ── Exits: sell a long / cover a short ────────────────────────────────────
    # Close the WHOLE position (never size it like an entry — a 27-share sizing on a 4-share
    # holding was rejected every scan) and cancel its stop/bracket orders first so the shares
    # aren't held for them. No protective stop is attached to an exit.
    if held is not None and _closes_position(signal.direction, held):
        return await _close_position(signal, held, source, quant_score)

    if side == "buy" and held is not None:
        result.update(action="skip", reason="Already holding position — skipping duplicate BUY")
        return result

    if side == "sell" and held is not None:
        result.update(action="skip", reason="Already short — skipping duplicate SHORT")
        return result

    if side == "sell" and held is None and not is_short:
        result.update(action="skip", reason="No position to sell — SELL only opens a short on a bear-market short setup")
        return result

    if is_short:
        block = _shortable_block_reason(signal.ticker)
        if block:
            result.update(action="skip", reason=block)
            return result

    atr      = stop_loss.calculate_atr(signal.ticker)
    risk_pct = get_param("risk_per_trade_pct") * size_mult
    if is_day or is_short:
        # Day trade (long or short): stop ~0.6 ATR (roughly half a day's range), target 2R
        from app.services.adaptive.daily_learner import get_day_params
        dp = get_day_params()          # learned nightly; defaults are DAY_STOP_ATR / DAY_REWARD_RISK
        stop_mult, target_mult = dp["stop_atr"], dp["stop_atr"] * dp["reward_risk"]
    else:
        stop_mult = max(0.8, get_param("atr_stop_multiplier") + stop_mult_adj)
        target_mult = None
    if atr > 0:
        qty = position_sizer.atr_based_size(equity, price, atr, risk_pct=risk_pct, stop_mult=stop_mult)
    else:
        qty = position_sizer.fixed_fraction_size(equity, price, risk_pct=risk_pct)
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
        result.update(action="dry_run", qty=qty, price=price, style=style,
                      stop=stop_loss.atr_stop_price(price, atr, side, stop_mult))
        return result

    # ── Submit to Alpaca ──────────────────────────────────────────────────────
    try:
        from app.services.trading_engine import broker
        stop_price = stop_loss.atr_stop_price(price, atr, side, stop_mult)
        stop_side  = "sell" if side == "buy" else "buy"

        order = None
        if (is_day or is_short) and atr > 0:
            target = stop_loss.atr_target_price(price, atr, target_mult, side)
            try:
                order = broker.submit_bracket_order(signal.ticker, qty, stop_price, target, side=side)
                logger.info(f"[DAYTRADE] {'SHORT' if is_short else 'LONG'} bracket submitted {signal.ticker} x{qty} stop={stop_price} tp={target}")
            except Exception as e:
                logger.warning(f"Bracket order failed for {signal.ticker} ({e}) — falling back to market+stop")
                order = None
        if order is None:
            order = broker.submit_market_order(signal.ticker, side, qty)
            logger.info(f"[{source.upper()}] Order submitted: {order}")
            broker.submit_stop_order(signal.ticker, stop_side, qty, stop_price)

        # Persist order with source tag
        await _save_order(
            ticker=signal.ticker, side=side, qty=qty, price=price,
            stop_price=stop_price, signal_id=None, source=source,
            quant_score=quant_score,
        )

        if is_day or is_short:
            from app.services.trading_engine import day_journal
            await day_journal.open_trade(
                signal.ticker, qty, price, stop_price,
                stop_loss.atr_target_price(price, atr, target_mult, side) if atr > 0 else None,
                bias=bias, quant_score=quant_score, side="short" if is_short else "long",
            )

        result.update(action="submitted", order=str(order), stop_price=stop_price)
    except Exception as e:
        logger.error(f"Order submission failed for {signal.ticker}: {e}")
        result.update(action="error", reason=str(e))

    return result


async def _close_position(signal: CompositeSignal, held: dict, source: str, quant_score: float | None) -> dict:
    """
    Exit a position completely: cancel every open order on the symbol (stop / bracket legs
    reserve the shares), then liquidate the whole position at market. Used for SELL on a
    long and BUY on a short.
    """
    result = {"ticker": signal.ticker, "direction": signal.direction, "action": None, "reason": None}
    qty = abs(held["qty"])
    is_short = held["qty"] < 0
    close_side = "buy" if is_short else "sell"
    price = held.get("current_price") or 0.0

    if _dry_run:
        logger.info(f"[DRY RUN] Would {'COVER' if is_short else 'SELL'} entire {signal.ticker} position ({qty} shares)")
        result.update(action="dry_run", qty=qty, price=price, reason="close whole position")
        return result

    try:
        from app.services.trading_engine import broker
        await asyncio.to_thread(broker.flatten_symbol, signal.ticker)
        logger.info(f"[{source.upper()}] Closed {signal.ticker}: {close_side} {qty} (whole position)")
        await _save_order(
            ticker=signal.ticker, side=close_side, qty=qty, price=price, stop_price=None,
            signal_id=None, source=source, quant_score=quant_score,
        )
        result.update(action="submitted", qty=qty, reason=f"closed whole position ({'cover' if is_short else 'sell'})")
    except Exception as e:
        logger.error(f"Close failed for {signal.ticker}: {e}")
        result.update(action="error", reason=str(e))
    return result


async def _save_order(ticker, side, qty, price, stop_price, signal_id, source, quant_score,
                       asset_class: str = "us_equity", contract_symbol: str | None = None):
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
                asset_class=asset_class,
                contract_symbol=contract_symbol,
            ))
            await db.commit()
    except Exception as e:
        logger.warning(f"Could not persist order record: {e}")


# ── Options execution ───────────────────────────────────────────────────────

async def _execute_options_signal(
    signal:      CompositeSignal,
    price:       float,
    equity:      float,
    held:        dict | None,
    source:      str,
    quant_score: float | None,
    size_mult:   float = 1.0,
) -> dict:
    """
    Options path for execute_signal — used when settings.enable_options_trading
    is on. BUY opens a long call, SELL opens a long put: a bearish view is
    expressed by buying a put, never by shorting shares. At most one options
    position is carried per ticker — an opposite-direction contract already
    held is closed rather than opened alongside it.
    """
    from app.services.trading_engine import broker, options_engine

    result = {"ticker": signal.ticker, "direction": signal.direction, "action": None, "reason": None}
    wants_type = "call" if signal.direction == "BUY" else "put"

    if held is not None:
        if held.get("option_type") is None:
            result.update(action="skip", reason="Holding an equity position on this ticker — skipping options order")
            return result

        if held["option_type"] == wants_type:
            result.update(action="skip", reason=f"Already holding a {wants_type} on {signal.ticker}")
            return result

        # Opposite-direction contract held → close it. A fresh position in
        # the new direction can open on a later scan once this is flat.
        contract_symbol = held["contract_symbol"]
        qty = abs(held["qty"])
        if _dry_run:
            result.update(action="dry_run", qty=qty, price=held.get("current_price"),
                          reason=f"would close {held['option_type']} ({contract_symbol})")
            return result
        try:
            order = broker.submit_market_order(contract_symbol, "sell", qty)
            await _save_order(
                ticker=signal.ticker, side="sell", qty=qty,
                price=held.get("current_price") or 0.0, stop_price=None,
                signal_id=None, source=source, quant_score=quant_score,
                asset_class="us_option", contract_symbol=contract_symbol,
            )
            result.update(action="submitted", order=str(order), reason=f"closed opposite {held['option_type']}")
        except Exception as e:
            logger.error(f"Options close failed for {contract_symbol}: {e}")
            result.update(action="error", reason=str(e))
        return result

    # No existing options position on this ticker → open one.
    contract = options_engine.select_best_strike(signal.ticker, price, signal.direction, settings.options_target_dte)
    if contract is None:
        result.update(action="skip", reason="No suitable options contract found")
        return result

    premium = contract["ask"] or contract["price"]
    if not premium or premium <= 0 or contract["bid"] <= 0:
        result.update(action="skip", reason="Contract has no bid/ask — illiquid, skipping")
        return result

    risk_pct = get_param("risk_per_trade_pct") * size_mult
    qty = options_engine.contract_size(equity, premium, risk_pct, settings.max_position_pct)
    if qty <= 0:
        result.update(action="skip", reason="Options sizer returned 0 contracts (premium too high for risk budget)")
        return result

    occ_symbol = options_engine.to_occ_symbol(
        signal.ticker, contract["expiry"], contract["option_type"], contract["strike"]
    )

    notional = qty * premium * 100
    if not portfolio_limits.check_position_size(notional, equity):
        result.update(action="skip",
                      reason=f"Position ${notional:.0f} exceeds max {settings.max_position_pct:.0%} of equity")
        return result

    if _dry_run:
        logger.info(
            f"[DRY RUN] Would BUY {qty}×{occ_symbol} @~${premium:.2f} "
            f"({contract['option_type']}, strike={contract['strike']}, exp={contract['expiry']})"
        )
        result.update(action="dry_run", qty=qty, price=premium, contract=occ_symbol,
                      expiry=contract["expiry"], strike=contract["strike"], option_type=contract["option_type"])
        return result

    try:
        order = broker.submit_market_order(occ_symbol, "buy", qty)
        logger.info(f"[{source.upper()}] Options order submitted: {order}")
        await _save_order(
            ticker=signal.ticker, side="buy", qty=qty, price=premium,
            stop_price=None, signal_id=None, source=source, quant_score=quant_score,
            asset_class="us_option", contract_symbol=occ_symbol,
        )
        result.update(action="submitted", order=str(order), contract=occ_symbol)
    except Exception as e:
        logger.error(f"Options order submission failed for {signal.ticker}: {e}")
        result.update(action="error", reason=str(e))

    return result
