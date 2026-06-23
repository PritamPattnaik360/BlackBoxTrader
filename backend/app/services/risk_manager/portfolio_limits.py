import logging
from app.config import settings

logger = logging.getLogger(__name__)
_peak_equity: float = 0.0
_day_start_equity: float = 0.0
_halted: bool = False


def update_equity(equity: float) -> None:
    global _peak_equity, _day_start_equity
    if equity > _peak_equity:
        _peak_equity = equity
    if _day_start_equity == 0:
        _day_start_equity = equity


def reset_day(equity: float) -> None:
    global _day_start_equity, _halted
    _day_start_equity = equity
    _halted = False


def is_halted(equity: float) -> bool:
    global _halted
    if _halted:
        return True
    if _peak_equity > 0:
        drawdown = (_peak_equity - equity) / _peak_equity
        if drawdown >= settings.max_drawdown_halt_pct:
            logger.warning(f"MAX DRAWDOWN HALT: drawdown={drawdown:.1%}")
            _halted = True
            return True
    if _day_start_equity > 0:
        day_loss = (_day_start_equity - equity) / _day_start_equity
        if day_loss >= settings.daily_loss_halt_pct:
            logger.warning(f"DAILY LOSS HALT: loss={day_loss:.1%}")
            _halted = True
            return True
    return False


def check_position_count(open_count: int) -> bool:
    return open_count < settings.max_open_positions


def check_position_size(notional: float, equity: float) -> bool:
    return notional <= equity * settings.max_position_pct
