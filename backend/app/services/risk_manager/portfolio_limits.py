"""
Portfolio circuit breaker — the "major loss" stop for the whole account.

Trips (blocks every new entry; the risk guard then liquidates open positions
when settings.flatten_on_halt is on) when any of:
  * daily loss   — equity down daily_loss_halt_pct from the prior close
  * drawdown     — equity down max_drawdown_halt_pct from its peak
  * market crash — SPY down market_crash_halt_pct from its prior close
  * manual       — the kill switch in Settings

Daily-loss and market-crash halts clear on their own the next trading day.
Drawdown and manual halts are sticky until resume() is called.

State is persisted so a restart can't silently clear a halt or the peak.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
STATE_PATH = Path(__file__).parents[4] / "data" / "risk_state.json"

_AUTO_CLEARING = {"daily_loss", "market_crash"}

_state: dict = {
    "peak_equity": 0.0,
    "day_start_equity": 0.0,
    "halted": False,
    "reason": None,       # daily_loss | drawdown | market_crash | manual
    "detail": None,
    "tripped_at": None,   # ISO timestamp (ET)
    "trip_date": None,    # ET date the halt tripped
}


def _today() -> str:
    return datetime.now(ET).date().isoformat()


def _load() -> None:
    try:
        _state.update(json.loads(STATE_PATH.read_text()))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"Could not load risk state: {e}")


def _save() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(_state, indent=2))
    except Exception as e:
        logger.warning(f"Could not save risk state: {e}")


_load()


def _trip(reason: str, detail: str) -> None:
    if _state["halted"]:
        return
    logger.critical(f"CIRCUIT BREAKER TRIPPED [{reason}]: {detail}")
    _state.update(halted=True, reason=reason, detail=detail,
                  tripped_at=datetime.now(ET).isoformat(timespec="seconds"), trip_date=_today())
    _save()


def _clear() -> None:
    _state.update(halted=False, reason=None, detail=None, tripped_at=None, trip_date=None)
    _save()


def update_equity(equity: float, day_start_equity: float | None = None) -> None:
    """Track peak equity. `day_start_equity` is the broker's prior-close equity."""
    changed = False
    if equity > _state["peak_equity"]:
        _state["peak_equity"] = equity
        changed = True
    if day_start_equity and day_start_equity != _state["day_start_equity"]:
        _state["day_start_equity"] = day_start_equity
        changed = True
    if changed:
        _save()


def evaluate(equity: float, spy_change_pct: float | None = None) -> bool:
    """Check every trip condition against the latest numbers. Returns is_halted()."""
    # A daily-loss / crash halt from a previous session expires at the next one
    if _state["halted"] and _state["reason"] in _AUTO_CLEARING and _state["trip_date"] != _today():
        logger.warning(f"Circuit breaker auto-reset (new session; was {_state['reason']})")
        _clear()
    if _state["halted"] or equity <= 0:
        return _state["halted"]

    peak = _state["peak_equity"]
    if peak > 0:
        drawdown = (peak - equity) / peak
        if drawdown >= settings.max_drawdown_halt_pct:
            _trip("drawdown", f"equity ${equity:,.0f} is {drawdown:.1%} below peak ${peak:,.0f}")

    start = _state["day_start_equity"]
    if not _state["halted"] and start > 0:
        day_loss = (start - equity) / start
        if day_loss >= settings.daily_loss_halt_pct:
            _trip("daily_loss", f"equity down {day_loss:.1%} today (${start:,.0f} -> ${equity:,.0f})")

    if not _state["halted"] and spy_change_pct is not None and spy_change_pct <= -settings.market_crash_halt_pct:
        _trip("market_crash", f"SPY {spy_change_pct:+.1%} on the day")

    return _state["halted"]


def is_halted(equity: float | None = None) -> bool:
    if equity is not None:
        update_equity(equity)
        return evaluate(equity)
    return _state["halted"]


def kill(detail: str = "manual kill switch") -> None:
    _trip("manual", detail)


def resume(current_equity: float | None = None) -> None:
    """Clear the halt. Re-bases the peak so a drawdown halt doesn't re-trip at once."""
    if current_equity:
        _state["peak_equity"] = current_equity
    logger.warning(f"Circuit breaker resumed (was {_state['reason']})")
    _clear()


def status() -> dict:
    return dict(_state)


def check_position_count(open_count: int) -> bool:
    return open_count < settings.max_open_positions


def check_position_size(notional: float, equity: float) -> bool:
    return notional <= equity * settings.max_position_pct
