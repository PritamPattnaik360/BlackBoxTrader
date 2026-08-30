"""
Market regime detector.
Downloads recent SPY data and classifies the current environment so the
adaptive engine can apply regime-specific parameter overlays.
"""
import logging

logger = logging.getLogger(__name__)

REGIMES = (
    "normal", "high_volatility", "low_volatility", "trending_up", "trending_down",
    "volatile_trending_up", "volatile_trending_down",
)

_cached_regime: str = "normal"


def get_current_regime() -> str:
    """Return the last detected regime without re-fetching (non-blocking)."""
    return _cached_regime


def detect_regime() -> str:
    """
    Returns one of REGIMES (normal, high_volatility, low_volatility, trending_up,
    trending_down, volatile_trending_up, volatile_trending_down).
    Falls back to 'normal' on any error so the app never blocks on network issues.
    """
    try:
        import pandas as pd
        import yfinance as yf
        raw = yf.download("SPY", period="1y", progress=False, auto_adjust=True)
        if raw.empty:
            return "normal"

        close = raw["Close"]
        # Recent yfinance versions return a single-column, ticker-labeled
        # DataFrame here (not a bare Series) even for one symbol — collapse
        # it so downstream float(...) calls get scalars, not one-row Series.
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        spy = close.dropna()
        if len(spy) < 50:
            return "normal"

        daily_returns = spy.pct_change().dropna()
        # Annualised 20-day rolling vol
        recent_vol = float(daily_returns.tail(20).std() * (252 ** 0.5))

        # Trend: compare 50-day vs 200-day SMA
        ma50  = float(spy.tail(50).mean())
        ma200 = float(spy.tail(200).mean()) if len(spy) >= 200 else float(spy.mean())
        current = float(spy.iloc[-1])

        trending_up   = current > ma200 and ma50 > ma200
        trending_down = current < ma200 and ma50 < ma200

        if recent_vol > 0.25:
            # Elevated vol AND a confirmed trend = a real breakout, not chop.
            if trending_up:
                regime = "volatile_trending_up"
            elif trending_down:
                regime = "volatile_trending_down"
            else:
                regime = "high_volatility"
        elif recent_vol < 0.10:
            regime = "low_volatility"
        elif trending_up:
            regime = "trending_up"
        elif trending_down:
            regime = "trending_down"
        else:
            regime = "normal"

        global _cached_regime
        _cached_regime = regime
        return regime

    except Exception as e:
        logger.warning(f"Regime detection failed, defaulting to normal: {e}")
        return "normal"
