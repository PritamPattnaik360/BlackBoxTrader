"""
Day-trading monitor API: the live day-trade settings plus performance stats
(winners vs losers, exit reasons, daily P&L) computed from the day-trade journal.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.day_trade import DayTrade

router = APIRouter(prefix="/day-trading", tags=["day-trading"])
ET = ZoneInfo("America/New_York")

FLATTEN_TIME_ET = "15:50"   # see core/scheduler.py (retry at 15:56)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _et_day(dt: datetime) -> str:
    return _aware(dt).astimezone(ET).date().isoformat()


def _stats(trades: list[DayTrade]) -> dict:
    """Win/loss statistics for a set of CLOSED trades (pnl known)."""
    closed = [t for t in trades if t.status == "closed" and t.pnl is not None]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)
    n = len(closed)
    return {
        "closed": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "net_pnl": round(gross_win + gross_loss, 2),
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_win / abs(gross_loss), 2) if gross_loss < 0 else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(gross_loss / len(losses), 2) if losses else None,
        "expectancy": round((gross_win + gross_loss) / n, 2) if n else None,
        "best": round(max((t.pnl for t in closed), default=0.0), 2) if n else None,
        "worst": round(min((t.pnl for t in closed), default=0.0), 2) if n else None,
        "avg_hold_min": round(sum((t.held_minutes or 0) for t in closed) / n, 1) if n else None,
    }


def _row(t: DayTrade) -> dict:
    return {
        "id": t.id, "ticker": t.ticker, "status": t.status, "qty": t.qty,
        "side": getattr(t, "side", None) or "long",
        "entry_price": t.entry_price, "stop_price": t.stop_price, "target_price": t.target_price,
        # Timestamps are stored as naive UTC; send them with an explicit offset so browsers
        # convert to the viewer's local time instead of reading them as local already.
        "entry_time": _aware(t.entry_time).isoformat() if t.entry_time else None,
        "exit_price": t.exit_price,
        "exit_time": _aware(t.exit_time).isoformat() if t.exit_time else None,
        "pnl": t.pnl, "pnl_pct": t.pnl_pct, "exit_reason": t.exit_reason,
        "held_minutes": t.held_minutes, "bias": t.bias, "quant_score": t.quant_score,
        "outcome": ("open" if t.status == "open" else "win" if (t.pnl or 0) > 0 else "loss"),
    }


def _settings_payload() -> dict:
    from app.services.adaptive.daily_learner import get_day_params, DAY_DEFAULTS, load_state
    from app.services.adaptive.adaptive_engine import get_param
    from app.services.trading_engine.executor import is_autonomous, is_dry_run
    from app.services.quant_engine.signal_combiner import _market_is_open

    learned = get_day_params()
    history = load_state().get("history", [])
    last_note = None
    if history:
        notes = [r for r in history[-1].get("report", []) if "day-trade" in r or "stop" in r or "reward" in r]
        last_note = {"date": history[-1].get("date"), "notes": notes[-3:]}

    g = lambda name, default: getattr(settings, name, default)   # tolerate older configs
    return {
        "autopilot": is_autonomous(),
        "execution_live": not is_dry_run(),
        "market_open": _market_is_open(),
        "trading_mode": settings.trading_mode,
        "entry_rules": [
            {"key": "day_trade_only", "label": "Day-trade-only mode", "value": bool(g("day_trade_only", True)),
             "help": "Every autopilot BUY must be a same-day trade; no overnight/swing entries.", "env": "DAY_TRADE_ONLY"},
            {"key": "min_score", "label": "Min composite score", "value": g("day_trade_min_score", None),
             "help": "Hard floor: signals scoring below this never open a day trade.", "env": "DAY_TRADE_MIN_SCORE"},
            {"key": "min_vwap", "label": "Min VWAP score", "value": g("day_trade_min_vwap", None),
             "help": "Price must be far enough above session VWAP to confirm the move.", "env": "DAY_TRADE_MIN_VWAP"},
            {"key": "entry_cutoff", "label": "Last entry (ET)", "value": g("day_trade_entry_cutoff", "15:30"),
             "help": "No new day-trade entries after this time.", "env": "DAY_TRADE_ENTRY_CUTOFF"},
            {"key": "short_day_trades", "label": "Short in bear markets", "value": bool(g("enable_short_day_trades", False)),
             "help": "When the market bias is bear, strong intraday breakdowns are shorted (stop above, "
                     "target below, covered by 15:50 ET). Needs a shortable, easy-to-borrow stock.", "env": "ENABLE_SHORT_DAY_TRADES"},
            {"key": "allow_short_live", "label": "Allow shorts in LIVE mode", "value": bool(g("allow_short_live", False)),
             "help": "Safety lock: shorting real money is blocked unless this is on.", "env": "ALLOW_SHORT_LIVE"},
            {"key": "learned_min_score", "label": "Learned min intraday score", "value": learned["min_intraday_score"],
             "default": DAY_DEFAULTS["min_intraday_score"],
             "help": "Raised automatically by the nightly learner if day trades lose money.", "env": None},
        ],
        "exit_rules": [
            {"key": "stop_atr", "label": "Stop distance (ATR)", "value": learned["stop_atr"],
             "default": DAY_DEFAULTS["stop_atr"],
             "help": "Stop-loss = this many daily ATRs below entry. Tuned nightly.", "env": None},
            {"key": "reward_risk", "label": "Reward : risk", "value": learned["reward_risk"],
             "default": DAY_DEFAULTS["reward_risk"],
             "help": "Take-profit = stop distance × this. Tuned nightly.", "env": None},
            {"key": "flatten", "label": "Forced exit (ET)", "value": FLATTEN_TIME_ET,
             "help": "Any day trade still open is closed at this time (retry at 15:56).", "env": None},
        ],
        "risk_rules": [
            {"key": "risk_per_trade", "label": "Risk per trade", "value": round(get_param("risk_per_trade_pct"), 5),
             "help": "Share of equity risked on each trade (adaptive; scaled by market bias).", "env": "RISK_PER_TRADE_PCT"},
            {"key": "max_position_pct", "label": "Max position size", "value": settings.max_position_pct,
             "help": "Largest single position as a share of equity.", "env": "MAX_POSITION_PCT"},
            {"key": "max_open_positions", "label": "Max open positions", "value": settings.max_open_positions,
             "help": "Cap on simultaneous positions.", "env": "MAX_OPEN_POSITIONS"},
            {"key": "daily_loss_halt", "label": "Daily loss halt", "value": settings.daily_loss_halt_pct,
             "help": "Circuit breaker: stop entering if the day's P&L falls past this.", "env": "DAILY_LOSS_HALT_PCT"},
            {"key": "pdt", "label": "Pattern-day-trader guard", "value": "3 trades / 5 days under $25k",
             "help": "Entries are skipped when the account would breach the PDT limit.", "env": None},
        ],
        "learning": {
            "enabled": bool(g("learning_enabled", True)),
            "last_review": last_note,
            "note": "Nightly review (16:30 ET) tunes stop, reward:risk and min intraday score once there are "
                    "15+ closed trades over 3+ days.",
        },
    }


@router.get("")
async def day_trading_overview(limit: int = 300, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DayTrade).order_by(desc(DayTrade.entry_time)))).scalars().all()

    today = datetime.now(ET).date()
    week_start = (today - timedelta(days=6)).isoformat()
    today_s = today.isoformat()

    periods = {
        "today": [t for t in rows if _et_day(t.entry_time) == today_s],
        "week": [t for t in rows if _et_day(t.entry_time) >= week_start],
        "all": rows,
    }

    # Daily series (ET trading day), oldest first, with running total
    by_day: dict[str, list[DayTrade]] = defaultdict(list)
    for t in rows:
        by_day[_et_day(t.entry_time)].append(t)
    daily, running = [], 0.0
    for day in sorted(by_day):
        closed = [t for t in by_day[day] if t.status == "closed" and t.pnl is not None]
        pnl = round(sum(t.pnl for t in closed), 2)
        running = round(running + pnl, 2)
        daily.append({
            "day": day, "trades": len(by_day[day]), "closed": len(closed),
            "wins": sum(1 for t in closed if t.pnl > 0),
            "losses": sum(1 for t in closed if t.pnl <= 0),
            "pnl": pnl, "cumulative": running,
        })

    # Exit-reason breakdown (closed trades)
    closed_all = [t for t in rows if t.status == "closed" and t.pnl is not None]
    reasons: dict[str, dict] = {}
    for t in closed_all:
        r = reasons.setdefault(t.exit_reason or "unknown", {"count": 0, "wins": 0, "pnl": 0.0})
        r["count"] += 1
        r["wins"] += 1 if t.pnl > 0 else 0
        r["pnl"] = round(r["pnl"] + t.pnl, 2)

    # Per-ticker results
    tickers: dict[str, dict] = {}
    for t in closed_all:
        r = tickers.setdefault(t.ticker, {"ticker": t.ticker, "trades": 0, "wins": 0, "pnl": 0.0})
        r["trades"] += 1
        r["wins"] += 1 if t.pnl > 0 else 0
        r["pnl"] = round(r["pnl"] + t.pnl, 2)
    ticker_list = sorted(tickers.values(), key=lambda r: r["pnl"], reverse=True)

    return {
        "settings": _settings_payload(),
        "stats": {k: _stats(v) for k, v in periods.items()},
        "open_trades": sum(1 for t in rows if t.status == "open"),
        "daily": daily[-45:],
        "exit_reasons": reasons,
        "tickers": {"best": ticker_list[:5], "worst": [r for r in ticker_list[::-1][:5] if r["pnl"] < 0]},
        "trades": [_row(t) for t in rows[:limit]],
    }
