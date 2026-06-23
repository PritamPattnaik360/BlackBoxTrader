import logging
from app.config import settings

logger = logging.getLogger(__name__)


def fixed_fraction_size(equity: float, current_price: float, risk_pct: float | None = None) -> int:
    """Risk risk_pct (or settings default) of equity; return whole share count."""
    pct = risk_pct if risk_pct is not None else settings.risk_per_trade_pct
    risk_amount = equity * pct
    if current_price <= 0:
        return 0
    shares = int(risk_amount / current_price)
    return max(shares, 1)


def atr_based_size(equity: float, current_price: float, atr: float, risk_pct: float | None = None) -> int:
    """Size position so that 2*ATR stop = risk_pct of equity."""
    pct = risk_pct if risk_pct is not None else settings.risk_per_trade_pct
    risk_amount = equity * pct
    stop_distance = 2.0 * atr
    if stop_distance <= 0 or current_price <= 0:
        return fixed_fraction_size(equity, current_price, risk_pct=pct)
    shares = int(risk_amount / stop_distance)
    return max(shares, 1)


def max_position_value(equity: float) -> float:
    return equity * settings.max_position_pct


def clamp_to_max(shares: int, current_price: float, equity: float) -> int:
    max_val = max_position_value(equity)
    if shares * current_price > max_val:
        shares = int(max_val / current_price)
    return max(shares, 1)
