"""
Signal outcome seeder.

Converts past BUY/SELL signals into LLM training samples by looking up
what the price actually did on the next trading day after the signal.

This runs completely without Alpaca credentials or autonomous mode —
it only uses yfinance for historical prices and the existing signal
rows already stored in the DB by signal_scan.

Lifecycle:
  - Fires once at startup (drains the backlog of existing signals)
  - Runs every 30 minutes via the scheduler to catch newly-aged signals
  - Skips signals already processed (tracks by signal_id in metadata)
  - Skips signals < MIN_AGE_HOURS old (next-day close may not exist yet)
  - Processes BATCH_LIMIT signals per run to avoid blocking the event loop
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.signal import Signal
from app.models.advisor import LlmTrainingSample

logger = logging.getLogger(__name__)

ET             = ZoneInfo("America/New_York")
MIN_AGE_HOURS  = 26     # wait >1 trading day so next-day close exists
MAX_AGE_DAYS   = 60     # ignore very old signals (stale market context)
BATCH_LIMIT    = 100    # signals per scheduler tick


# ── Public entry point ────────────────────────────────────────────────────────

async def run_signal_outcome_seeder() -> int:
    """
    Evaluate past signals against next-day prices and save training samples.
    Returns the number of new samples saved.
    """
    now            = datetime.now(timezone.utc)
    min_cutoff     = now - timedelta(hours=MIN_AGE_HOURS)
    max_cutoff     = now - timedelta(days=MAX_AGE_DAYS)

    processed_ids  = await _get_processed_signal_ids()

    async with AsyncSessionLocal() as db:
        q = (
            select(Signal)
            .where(
                Signal.direction.in_(["BUY", "SELL"]),
                Signal.created_at <= min_cutoff,
                Signal.created_at >= max_cutoff,
            )
            .order_by(Signal.created_at.desc())
            .limit(BATCH_LIMIT * 5)          # over-fetch; filter in Python
        )
        result  = await db.execute(q)
        all_sigs = result.scalars().all()

    # Filter out already-processed, then take the batch
    pending = [s for s in all_sigs if s.id not in processed_ids][:BATCH_LIMIT]

    if not pending:
        logger.debug("Signal seeder: nothing new to process")
        return 0

    logger.info(f"Signal seeder: processing {len(pending)} signal(s)...")

    # Group by ticker to minimise yfinance round-trips
    by_ticker: dict[str, list[Signal]] = {}
    for sig in pending:
        by_ticker.setdefault(sig.ticker, []).append(sig)

    saved = 0
    for ticker, sigs in by_ticker.items():
        # Determine the date window we need to cover all signals for this ticker
        oldest = min(s.created_at for s in sigs)
        start  = (oldest.astimezone(ET).date() - timedelta(days=3))
        end    = (datetime.now(ET).date()       + timedelta(days=2))

        df = await asyncio.to_thread(_fetch_daily, ticker, str(start), str(end))
        if df is None or df.empty:
            continue

        for sig in sigs:
            try:
                entry_px, exit_px = _prices_for_signal(df, sig.created_at)
                if entry_px is None or exit_px is None:
                    continue
                await _save_sample(sig, entry_px, exit_px)
                saved += 1
            except Exception as exc:
                logger.debug("Seeder skip %s #%d: %s", ticker, sig.id, exc)

    if saved:
        logger.info("Signal seeder: saved %d new training sample(s)", saved)
    return saved


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_processed_signal_ids() -> set[int]:
    """Return signal IDs that already have a seeder-generated training sample."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LlmTrainingSample.metadata_)
            .where(LlmTrainingSample.source == "signal_seeder")
        )
        ids: set[int] = set()
        for (meta,) in result.all():
            if isinstance(meta, dict):
                sid = meta.get("signal_id")
                if sid is not None:
                    ids.add(int(sid))
    return ids


def _fetch_daily(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Download daily OHLCV and return with a date index (no time component)."""
    try:
        df = yf.download(ticker, start=start, end=end, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower() for c in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]
        df.index = pd.to_datetime(df.index).date
        return df
    except Exception as exc:
        logger.debug("yfinance download failed for %s: %s", ticker, exc)
        return None


def _prices_for_signal(
    df: pd.DataFrame,
    signal_dt: datetime,
) -> tuple[float | None, float | None]:
    """
    Return (entry_close, exit_close) where:
      entry = closing price on the signal's trading day (or next available)
      exit  = closing price on the following trading day
    """
    sig_date = signal_dt.astimezone(ET).date()
    dates    = sorted(df.index)

    # First trading day on or after the signal date
    entry_dates = [d for d in dates if d >= sig_date]
    if not entry_dates:
        return None, None
    entry_date = entry_dates[0]
    entry_px   = float(df.loc[entry_date, "close"])

    # Next trading day after entry
    exit_dates = [d for d in dates if d > entry_date]
    if not exit_dates:
        return None, None
    exit_date = exit_dates[0]
    exit_px   = float(df.loc[exit_date, "close"])

    return entry_px, exit_px


async def _save_sample(sig: Signal, entry_px: float, exit_px: float) -> None:
    raw_return  = (exit_px - entry_px) / entry_px
    pnl_pct     = raw_return if sig.direction == "BUY" else -raw_return
    was_correct = pnl_pct > 0

    # Higher absolute PnL = more informative sample
    quality = min(0.3 + abs(pnl_pct) * 10, 1.0)

    news_str  = f"{sig.news_score:+.3f}" if sig.news_score is not None else "n/a"
    pnl_str   = f"{pnl_pct * 100:+.2f}%"

    instruction = (
        f"You are analyzing a {sig.direction} signal for {sig.ticker}.\n"
        f"Signal score: {sig.composite_score:+.3f}, confidence: {sig.confidence:.2f}\n"
        f"News score: {news_str}\n"
        f"Entry price: ${entry_px:.2f}\n"
        f"Should this {sig.direction} trade on {sig.ticker} be executed?"
    )

    if was_correct:
        response = (
            f"Yes. The {sig.direction} signal on {sig.ticker} was correct — "
            f"price moved {pnl_str} the next trading day. "
            f"Combined score {sig.composite_score:+.3f} with confidence "
            f"{sig.confidence:.2f} identified the direction accurately. "
            f"Execute similar high-confidence setups."
        )
    else:
        response = (
            f"No. The {sig.direction} signal on {sig.ticker} was incorrect — "
            f"price moved {pnl_str} against the trade the next trading day. "
            f"Score {sig.composite_score:+.3f} with confidence {sig.confidence:.2f} "
            f"failed to predict direction. Require stronger confirmation before trading."
        )

    async with AsyncSessionLocal() as db:
        db.add(LlmTrainingSample(
            instruction=instruction,
            response=response,
            ticker=sig.ticker,
            quality=quality,
            was_correct=was_correct,
            pnl_pct=round(pnl_pct, 6),
            source="signal_seeder",
            metadata_={
                "signal_id":       sig.id,
                "direction":       sig.direction,
                "composite_score": sig.composite_score,
                "news_score":      sig.news_score,
                "entry_px":        entry_px,
                "exit_px":         exit_px,
            },
        ))
        await db.commit()
