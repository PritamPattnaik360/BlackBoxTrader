"""
Loss guard for new day-trade entries — the bot's memory of what just failed.

Two rules, both based on stop-outs (a stop means the trade thesis was wrong, so re-entering the
same name straight away is buying into a move that is still working against us):

  1. A ticker stopped out earlier today is not re-entered today.
  2. A ticker stopped out STOCK_STOPS_WINDOW or more times in the last 5 calendar days is paused
     until the oldest of those stops ages out.

Plus a market-wide brake: after MAX_STOPS_PER_DAY stop-outs in one session, no new day trades that
day (the tape is chopping stops; more entries just feed it).
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

MAX_STOPS_PER_DAY = 3
TICKER_STOPS_WINDOW = 2
WINDOW_DAYS = 5


def _et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def block_reason(ticker: str, stops: list[dict], now_et: datetime) -> str | None:
    """`stops`: recent stop-outs as {"ticker", "exit_time"}. None = entry allowed."""
    today = now_et.date()
    todays = [s for s in stops if _et(s["exit_time"]).date() == today]
    if any(s["ticker"] == ticker for s in todays):
        return f"{ticker} was stopped out earlier today — no re-entry"
    if len(todays) >= MAX_STOPS_PER_DAY:
        return f"{len(todays)} stop-outs today (limit {MAX_STOPS_PER_DAY}) — no more day trades this session"
    cutoff = now_et - timedelta(days=WINDOW_DAYS)
    recent = [s for s in stops if s["ticker"] == ticker and _et(s["exit_time"]) >= cutoff]
    if len(recent) >= TICKER_STOPS_WINDOW:
        return f"{ticker} stopped out {len(recent)}x in the last {WINDOW_DAYS} days — paused"
    return None


async def recent_stops() -> list[dict]:
    """Stop-outs from the last WINDOW_DAYS days (empty on any error, so a DB hiccup never blocks trading)."""
    try:
        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.models.day_trade import DayTrade
        since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS + 2)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(DayTrade).where(DayTrade.exit_reason == "stop", DayTrade.exit_time >= since)
            )).scalars().all()
        return [{"ticker": r.ticker, "exit_time": r.exit_time} for r in rows if r.exit_time]
    except Exception as e:
        logger.warning(f"Loss guard could not load recent stops: {e}")
        return []
