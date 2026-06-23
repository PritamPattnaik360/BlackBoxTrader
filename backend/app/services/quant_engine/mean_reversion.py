"""
Bollinger Band z-score with Ornstein-Uhlenbeck half-life filter.

The OU half-life test rejects stocks that don't revert fast enough to be
tradeable — if reversion takes > 20 days, the signal is zeroed out.

Score convention: negative z-score (price below mean) → positive score (buy).
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BB_WINDOW     = 20     # Bollinger Band lookback
MIN_REQUIRED  = 30
MAX_HALF_LIFE = 20.0   # days; longer → too slow to trade


def compute(prices: pd.Series) -> float:
    """
    Args:
        prices: Daily close price series.
    Returns:
        Float in (-1, 1). Positive = oversold / likely to revert upward.
    """
    try:
        closes = prices.dropna()
        if len(closes) < MIN_REQUIRED:
            return 0.0

        # ── OU half-life test ──────────────────────────────────────────────
        half_life = _ou_half_life(closes)
        if half_life is None or half_life > MAX_HALF_LIFE:
            return 0.0   # series doesn't mean-revert fast enough

        # ── Bollinger Band z-score ─────────────────────────────────────────
        window = closes.iloc[-BB_WINDOW:]
        mean   = float(window.mean())
        std    = float(window.std())

        if std < 1e-9:
            return 0.0

        current = float(closes.iloc[-1])
        z = (current - mean) / std

        # Flip sign: price below mean (z < 0) → buy signal (positive score)
        score = -z / 2.0   # ±2σ → ±1.0
        return max(-1.0, min(1.0, score))

    except Exception as e:
        logger.debug(f"Mean reversion computation failed: {e}")
        return 0.0


def _ou_half_life(prices: pd.Series) -> float | None:
    """
    Fit AR(1) model and compute mean-reversion half-life.
    y[t] = θ·y[t-1] + ε  → half_life = log(2) / |log(θ)|
    """
    try:
        y      = prices.values.astype(float)
        y_lag  = y[:-1]
        y_cur  = y[1:]

        # OLS: y_cur = a + b * y_lag
        A = np.vstack([np.ones(len(y_lag)), y_lag]).T
        result = np.linalg.lstsq(A, y_cur, rcond=None)
        b = float(result[0][1])   # AR(1) coefficient

        if b <= 0 or b >= 1:
            return None   # not mean-reverting

        half_life = math.log(2) / (-math.log(b))
        return half_life if half_life > 0 else None

    except Exception:
        return None
