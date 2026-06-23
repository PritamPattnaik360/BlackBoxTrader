"""
Technical composite signal: RSI(14) + MACD histogram + EMA(50/200) crossover.

All three are normalized to (-1, 1) and combined with fixed weights.
Positive composite → bullish technical picture → buy.
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_REQUIRED = 210   # need at least 200 days for EMA-200


def compute(prices: pd.Series) -> float:
    """
    Returns Float in (-1, 1). Positive = technically bullish.
    """
    try:
        closes = prices.dropna()
        if len(closes) < MIN_REQUIRED:
            return 0.0

        rsi_score  = _rsi_signal(closes)
        macd_score = _macd_signal(closes)
        ema_score  = _ema_crossover_signal(closes)

        composite = 0.40 * rsi_score + 0.35 * macd_score + 0.25 * ema_score
        return max(-1.0, min(1.0, composite))

    except Exception as e:
        logger.debug(f"Technical computation failed: {e}")
        return 0.0


# ── Component signals ─────────────────────────────────────────────────────────

def _rsi_signal(closes: pd.Series, period: int = 14) -> float:
    """RSI < 30 → +1 (oversold/buy), RSI > 70 → -1 (overbought/sell)."""
    delta     = closes.diff()
    gains     = delta.clip(lower=0)
    losses    = (-delta).clip(lower=0)
    avg_gain  = gains.ewm(com=period - 1, min_periods=period).mean()
    avg_loss  = losses.ewm(com=period - 1, min_periods=period).mean()
    rs        = avg_gain / avg_loss.replace(0, 1e-9)
    rsi       = 100 - (100 / (1 + rs))
    current_rsi = float(rsi.iloc[-1])

    # Normalize: (50 - RSI) / 50 → positive when oversold, negative when overbought
    score = (50.0 - current_rsi) / 50.0
    return max(-1.0, min(1.0, score))


def _macd_signal(closes: pd.Series) -> float:
    """MACD histogram: positive histogram → bullish, negative → bearish."""
    ema12  = closes.ewm(span=12, adjust=False).mean()
    ema26  = closes.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal

    current_hist = float(hist.iloc[-1])
    current_price = float(closes.iloc[-1])

    if current_price <= 0:
        return 0.0

    # Normalize by price to make it comparable across stocks
    normalized = current_hist / (current_price * 0.005)
    return max(-1.0, min(1.0, math.tanh(normalized)))


def _ema_crossover_signal(closes: pd.Series) -> float:
    """
    EMA(50) vs EMA(200) golden/death cross.
    Golden cross (EMA50 > EMA200) → positive score.
    Magnitude reflects how far apart the EMAs are.
    """
    ema50  = float(closes.ewm(span=50,  adjust=False).mean().iloc[-1])
    ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])

    if ema200 <= 0:
        return 0.0

    spread = (ema50 - ema200) / ema200
    # 1% spread → score ~0.10; 5% spread → score ~0.46
    return max(-1.0, min(1.0, math.tanh(spread * 10.0)))
