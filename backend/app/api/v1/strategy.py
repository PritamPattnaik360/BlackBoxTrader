"""
Strategy API — current market bias, the active algorithm profile, and the
stocks the universe screen is surfacing from the S&P 500 + growth list.
"""
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.day_trade import DayTrade

from app.services.strategy import market_bias
from app.services.universe import universe

router = APIRouter(prefix="/strategy", tags=["strategy"])


def _payload() -> dict:
    ctx = market_bias.get_context()
    profile = market_bias.get_profile(ctx["bias"])
    screen = universe.get_cached_screen() or {}
    return {
        "context": ctx,
        "profile": {
            "name": profile.name,
            "label": profile.label,
            "description": profile.description,
            "daily_weights": profile.daily_weights,
            "intraday_weights": profile.intraday_weights,
            "buy_threshold_adj": profile.buy_thr_adj,
            "sell_threshold_adj": profile.sell_thr_adj,
            "size_multiplier": profile.size_mult,
            "stop_multiplier_adj": profile.stop_mult_adj,
        },
        "universe": {
            "size": screen.get("universe_size"),
            "swing": screen.get("swing", []),
            "day": screen.get("day", []),
            "details": screen.get("details", {}),
            "screened_for_bias": screen.get("bias"),
        },
    }


@router.get("/context")
async def get_strategy_context():
    """Current bias + profile + last universe screen (no network calls)."""
    return _payload()


@router.post("/refresh")
async def refresh_strategy():
    """Force-recompute the market bias, then re-run the universe screen for it."""
    ctx = await asyncio.to_thread(market_bias.refresh_bias, True)
    await asyncio.to_thread(universe.screen, ctx["bias"], 15, 10, True)
    return _payload()


def _row(t: DayTrade) -> dict:
    return {
        "id": t.id, "ticker": t.ticker, "status": t.status, "qty": t.qty,
        "entry_price": t.entry_price, "stop_price": t.stop_price, "target_price": t.target_price,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "exit_price": t.exit_price,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "pnl": t.pnl, "pnl_pct": t.pnl_pct, "exit_reason": t.exit_reason,
        "held_minutes": t.held_minutes, "bias": t.bias,
    }


@router.get("/day-trades")
async def list_day_trades(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Day-trade journal (newest first) plus today's summary."""
    rows = (await db.execute(select(DayTrade).order_by(desc(DayTrade.entry_time)).limit(limit))).scalars().all()
    et = ZoneInfo("America/New_York")
    today = datetime.now(et).date()

    def entry_day(t):
        dt = t.entry_time if t.entry_time.tzinfo else t.entry_time.replace(tzinfo=timezone.utc)
        return dt.astimezone(et).date()

    todays = [t for t in rows if entry_day(t) == today]
    closed = [t for t in todays if t.status == "closed" and t.pnl is not None]
    wins = [t for t in closed if t.pnl > 0]
    return {
        "today": {
            "trades": len(todays),
            "open": sum(1 for t in todays if t.status == "open"),
            "closed": len(closed),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(closed), 3) if closed else None,
            "pnl": round(sum(t.pnl for t in closed), 2),
        },
        "trades": [_row(t) for t in rows],
    }
