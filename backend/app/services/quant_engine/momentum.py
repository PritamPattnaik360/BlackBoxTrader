"""
Jegadeesh-Titman 12-1 momentum factor (1993).

Uses the past 12 months of returns but skips the most recent month to avoid
the short-term reversal effect.  Score is sigmoid-normalized to (-1, 1).
Positive score → buy, negative → sell.
"""
import math
import logging
import pandas as pd

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 252   # ~12 months of trading days
SKIP_DAYS     = 21    # ~1 month  (skip to avoid short-term reversal)
MIN_REQUIRED  = 60    # minimum bars needed to return a meaningful signal


def compute(prices: pd.Series) -> float:
    """
    Args:
        prices: Daily close price series, at least LOOKBACK_DAYS long.
    Returns:
        Float in (-1, 1). Positive = upward momentum (buy signal).
    """
    try:
        closes = prices.dropna()
        if len(closes) < MIN_REQUIRED:
            return 0.0

        n = len(closes)
        end_idx   = -1               # today
        skip_idx  = -(SKIP_DAYS + 1) # 1 month ago
        start_idx = max(-(LOOKBACK_DAYS + 1), -n)  # 12 months ago

        p_now    = float(closes.iloc[end_idx])
        p_1m_ago = float(closes.iloc[skip_idx])
        p_12m_ago = float(closes.iloc[start_idx])

        if p_12m_ago <= 0 or p_1m_ago <= 0:
            return 0.0

        ret_12m = (p_1m_ago - p_12m_ago) / p_12m_ago   # 12-month return (skip last month)
        ret_1m  = (p_now   - p_1m_ago)  / p_1m_ago     # last-month return

        # Jegadeesh-Titman factor: 12m return minus short-term reversal
        momentum = ret_12m - ret_1m

        # Sigmoid normalization: 30% annual momentum → score ~0.85
        score = math.tanh(momentum * 3.0)
        return max(-1.0, min(1.0, score))

    except Exception as e:
        logger.debug(f"Momentum computation failed: {e}")
        return 0.0
