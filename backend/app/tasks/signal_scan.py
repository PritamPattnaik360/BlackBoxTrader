"""
Signal scan task.

Generates NLP + quant signals for every watchlist ticker.
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


async def run_signal_scan():
    logger.info("Running signal scan...")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
        tickers = [row.ticker for row in result.scalars().all()]

    if not tickers:
        logger.info("Watchlist empty — skipping scan")
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
    market_open = _is_market_hours()

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

            logger.info(
                f"{ticker}: nlp={nlp.composite_score:+.3f} "
                f"mom={quant.momentum_score:+.3f} "
                f"mr={quant.mean_reversion_score:+.3f} "
                f"tech={quant.technical_score:+.3f} "
                f"→ combined={quant.combined_score:+.3f} [{quant.direction}]"
            )

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
                )
                logger.info(f"Auto-execute {ticker}: {exec_result.get('action')} ({exec_result.get('reason', '')})")

            elif autonomous and not market_open and quant.direction != "HOLD":
                logger.info(f"Market closed — deferring {ticker} [{quant.direction}]")

        except Exception as e:
            logger.error(f"Signal scan error for {ticker}: {e}", exc_info=True)

    logger.info(
        f"Scan complete — {len(tickers)} tickers "
        f"[autonomous={'ON' if autonomous else 'OFF'}, "
        f"market={'OPEN' if market_open else 'CLOSED'}]"
    )
