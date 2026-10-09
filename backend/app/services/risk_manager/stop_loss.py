import pandas as pd
from app.config import settings
from app.services.market_data.yfinance_client import get_ohlcv


def calculate_atr(ticker: str, period: int = 14) -> float:
    try:
        df = get_ohlcv(ticker, period="3mo", interval="1d")
        if df.empty or len(df) < period + 1:
            return 0.0
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])
    except Exception:
        return 0.0


def atr_stop_price(entry_price: float, atr: float, side: str = "buy", mult: float | None = None) -> float:
    """ATR stop. `mult` defaults to the adaptive engine's learned multiplier
    (which the regime overlay adjusts), not the static config value."""
    if mult is None:
        from app.services.adaptive.adaptive_engine import get_param
        mult = get_param("atr_stop_multiplier")
    if side == "buy":
        return round(entry_price - mult * atr, 2)
    else:
        return round(entry_price + mult * atr, 2)


def atr_target_price(entry_price: float, atr: float, mult: float, side: str = "buy") -> float:
    """Take-profit `mult` ATRs away from entry."""
    if side == "buy":
        return round(entry_price + mult * atr, 2)
    return round(entry_price - mult * atr, 2)


def fixed_pct_stop(entry_price: float, pct: float = 0.02, side: str = "buy") -> float:
    if side == "buy":
        return round(entry_price * (1 - pct), 2)
    else:
        return round(entry_price * (1 + pct), 2)
