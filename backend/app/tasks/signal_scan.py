"""
Signal scan task.

Generates NLP + quant signals for the watchlist plus the best candidates
screened from the S&P 500 + growth-stock universe (see services/universe).
The market bias (bull / neutral / bear) is refreshed first and drives which
algorithm mix the signals use and which stocks the screen favours.
When autonomous mode is active AND market hours are open, the combined signal
is automatically executed — no user interaction required.
"""
import asyncio
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.db.session import AsyncSessionLocal
from app.services.nlp_engine.aggregator import generate_signal
from app.services.quant_engine.signal_combiner import analyze as quant_analyze
from app.services.trading_engine.executor import execute_signal, is_autonomous
from app.services.trading_engine.broker import get_account, get_positions
from app.models.signal import Signal
from app.models.watchlist import Watchlist
from sqlalchemy import select

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def _is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:          # Sat / Sun
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


async def _build_scan_list(market_open: bool) -> tuple[list[str], dict]:
    """Watchlist + top screened swing candidates (+ day-trade candidates during the session)."""
    from app.services.strategy import market_bias
    from app.services.universe import universe

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
        tickers = [row.ticker for row in result.scalars().all()]

    bias = market_bias.get_bias()
    picks: dict = {"swing": [], "day": []}
    try:
        screened = await asyncio.to_thread(universe.screen, bias)
        picks = {"swing": screened["swing"], "day": screened["day"] if market_open else []}
    except Exception as e:
        logger.warning(f"Universe screen failed — scanning watchlist only: {e}")

    for t in picks["swing"] + picks["day"]:
        if t not in tickers:
            tickers.append(t)
    return tickers, picks


async def run_signal_scan():
    from app.services.strategy import market_bias

    logger.info("Running signal scan...")
    market_open = _is_market_hours()

    ctx = await asyncio.to_thread(market_bias.refresh_bias)
    tickers, picks = await _build_scan_list(market_open)
    logger.info(
        f"Market bias={ctx['bias']} (VIX={ctx.get('vix')}) — scanning {len(tickers)} tickers "
        f"({len(picks['swing'])} swing + {len(picks['day'])} day picks from universe)"
    )

    if not tickers:
        logger.info("Nothing to scan — skipping")
        return

    try:
        account    = get_account()
        equity     = account["equity"]
        positions  = get_positions()
        open_count = len(positions)
    except Exception as e:
        logger.warning(f"Could not fetch account info: {e} — using defaults")
        equity     = 100_000.0
        open_count = 0

    autonomous  = is_autonomous()

    scan_results: list[tuple] = []   # (ticker, nlp, quant) for every successful scan
    trades_submitted = 0

    for ticker in tickers:
        try:
            # ── NLP signal ────────────────────────────────────────────────
            nlp = await generate_signal(ticker)

            # ── Quant analysis (runs momentum/mean_rev/technical in threads) ──
            quant = await quant_analyze(ticker, nlp.composite_score, nlp.confidence)

            # ── Persist the enriched signal to DB ─────────────────────────
            async with AsyncSessionLocal() as db:
                raw = nlp.raw_headlines or []
                # Append quant component summary for dashboard display
                quant_summary = {
                    "_quant": quant.components,
                    "headlines": raw,
                }
                db_signal = Signal(
                    ticker=quant.ticker,
                    composite_score=quant.combined_score,
                    confidence=quant.confidence,
                    direction=quant.direction,
                    source_count=nlp.source_count,
                    news_score=nlp.news_score,
                    reddit_score=None,
                    raw_headlines=quant_summary,
                )
                db.add(db_signal)
                await db.commit()

            if quant.intraday_active:
                logger.info(
                    f"{ticker}: intraday={quant.intraday_score:+.3f} "
                    f"nlp={nlp.composite_score:+.3f} "
                    f"mom={quant.momentum_score:+.3f} "
                    f"→ combined={quant.combined_score:+.3f} [{quant.direction}]"
                    f" [VWAP={quant.components.get('intraday_vwap', 0):+.3f}"
                    f" ORB={quant.components.get('intraday_orb', 0):+.3f}"
                    f" RVOL={quant.components.get('rvol', 1):.2f}x]"
                )
            else:
                logger.info(
                    f"{ticker}: nlp={nlp.composite_score:+.3f} "
                    f"mom={quant.momentum_score:+.3f} "
                    f"mr={quant.mean_reversion_score:+.3f} "
                    f"tech={quant.technical_score:+.3f} "
                    f"→ combined={quant.combined_score:+.3f} [{quant.direction}]"
                )

            scan_results.append((ticker, nlp, quant))

            # ── Autonomous execution gate ──────────────────────────────────
            if autonomous and market_open and quant.direction != "HOLD":
                # Build a minimal CompositeSignal using the combined score
                from app.services.nlp_engine.aggregator import CompositeSignal
                from datetime import timezone
                merged_signal = CompositeSignal(
                    ticker=quant.ticker,
                    composite_score=quant.combined_score,
                    confidence=quant.confidence,
                    direction=quant.direction,
                    source_count=nlp.source_count,
                    news_score=nlp.news_score,
                    reddit_score=None,
                    raw_headlines=nlp.raw_headlines,
                    created_at=datetime.now(timezone.utc),
                )
                exec_result = await execute_signal(
                    merged_signal, open_count, equity,
                    source="auto",
                    quant_score=quant.combined_score,
                    style=quant.trade_style,
                    size_mult=quant.size_mult,
                    stop_mult_adj=quant.stop_mult_adj,
                    bias=quant.bias,
                )
                action = exec_result.get("action")
                logger.info(f"Auto-execute {ticker}: {action} ({exec_result.get('reason', '')})")
                if action in ("submitted", "dry_run"):
                    trades_submitted += 1
                    if quant.direction == "BUY":
                        open_count += 1   # keep the position-count gate honest within one scan

            elif autonomous and not market_open and quant.direction != "HOLD":
                logger.info(f"Market closed — deferring {ticker} [{quant.direction}]")

        except Exception as e:
            logger.error(f"Signal scan error for {ticker}: {e}", exc_info=True)

    # ── Mandatory learning trade ───────────────────────────────────────────────
    # If autonomous mode is on, the market is open, and the normal signal gate
    # let nothing through (all HOLD), force exactly one trade on the ticker with
    # the highest absolute combined score so the RL system always receives
    # outcome data and can start adapting its thresholds.
    # Skipped in a bear market: forcing a long there just to generate data is
    # exactly the trade the bear profile is trying to avoid.
    if (autonomous and market_open and trades_submitted == 0 and scan_results
            and market_bias.get_bias() != "bear"):
        from app.services.nlp_engine.aggregator import CompositeSignal
        from datetime import timezone

        best_ticker, best_nlp, best_quant = max(
            scan_results, key=lambda x: abs(x[2].combined_score)
        )
        forced_direction = "BUY" if best_quant.combined_score >= 0 else "SELL"
        logger.warning(
            f"[LEARNING] No orders placed this scan — forcing mandatory "
            f"{forced_direction} on {best_ticker} "
            f"(score={best_quant.combined_score:+.4f}) to seed RL outcomes"
        )
        forced_signal = CompositeSignal(
            ticker=best_ticker,
            composite_score=best_quant.combined_score,
            confidence=best_quant.confidence,
            direction=forced_direction,
            source_count=best_nlp.source_count,
            news_score=best_nlp.news_score,
            reddit_score=None,
            raw_headlines=best_nlp.raw_headlines,
            created_at=datetime.now(timezone.utc),
        )
        exec_result = await execute_signal(
            forced_signal, open_count, equity,
            source="learning",
            quant_score=best_quant.combined_score,
            size_mult=best_quant.size_mult * 0.5,   # learning trades are small by design
            style=best_quant.trade_style,
            bias=best_quant.bias,
            stop_mult_adj=best_quant.stop_mult_adj,
        )
        logger.info(
            f"[LEARNING] Forced trade result: {exec_result.get('action')} "
            f"({exec_result.get('reason', '')})"
        )

    logger.info(
        f"Scan complete [{ctx['bias']}] — {len(tickers)} tickers, {trades_submitted} submitted "
        f"[autonomous={'ON' if autonomous else 'OFF'}, "
        f"market={'OPEN' if market_open else 'CLOSED'}]"
    )
