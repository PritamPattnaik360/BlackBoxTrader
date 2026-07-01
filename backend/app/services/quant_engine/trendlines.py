"""
Trend line analysis via swing pivot detection.

Real day traders draw trend lines by connecting swing highs (resistance)
and swing lows (support) to identify the prevailing direction and key
breakout/breakdown levels. This module automates that process:

  1. Detect swing highs and lows using a local-extremum algorithm
  2. Fit a linear regression through the most recent 2-3 pivots of each type
  3. Project the support and resistance lines forward to the current bar
  4. Score based on:
     - Breakout above projected resistance  → +0.7 to +1.0 (strong bullish)
     - Breakdown below projected support    → -0.7 to -1.0 (strong bearish)
     - Slope of support line (rising = uptrend, falling = downtrend)
     - Channel position (where price sits between support and resistance)

Works with any OHLCV DataFrame: daily bars for swing context, 5-min bars
for intraday micro-trends.  Pass swing_n=5 for daily, swing_n=3 for 5-min.

Returns a score in [-1, 1] plus metadata (support/resistance levels,
trend direction, breakout/breakdown flags) used by the LLM prompt.
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MIN_BARS      = 25     # minimum bars before running analysis
_SWING_N       = 5      # bars on each side defining a swing high/low (daily)
_LOOKBACK      = 90     # only scan the most recent N bars for pivots
_RECENT_PIVOTS = 3      # how many of the most recent pivots to fit the line through


def compute(
    df: pd.DataFrame,
    swing_n: int  = _SWING_N,
    lookback: int = _LOOKBACK,
) -> dict:
    """
    Args:
        df:       OHLCV DataFrame with lowercase columns (open/high/low/close/volume).
                  Works for daily or intraday bars.
        swing_n:  Bars on each side of a pivot.  Use 5 for daily, 3 for 5-min.
        lookback: Only use the most recent N bars for pivot detection.

    Returns dict:
        score            float  (-1 to 1) — primary signal fed to the combiner
        support_level    float  — projected support price at latest bar
        resistance_level float  — projected resistance price at latest bar
        trend_dir        str    — "uptrend" | "downtrend" | "sideways"
        breakout         bool   — price closed above resistance
        breakdown        bool   — price closed below support
        slope_score      float  — direction component (negative = downtrend)
        channel_score    float  — position within channel
    """
    _empty = {
        "score": 0.0, "support_level": 0.0, "resistance_level": 0.0,
        "trend_dir": "sideways", "breakout": False, "breakdown": False,
        "slope_score": 0.0, "channel_score": 0.0,
    }

    try:
        df = df.dropna(subset=["high", "low", "close"])
        if len(df) < _MIN_BARS:
            return _empty

        # Work on a fixed-length window, re-indexed 0..n-1
        win = df.iloc[-lookback:].copy().reset_index(drop=True)

        highs = win["high"]
        lows  = win["low"]

        swing_highs = _find_swing_highs(highs, swing_n)
        swing_lows  = _find_swing_lows(lows,  swing_n)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return _empty

        # Fit lines through the most recent pivots
        res_pts = swing_highs[-_RECENT_PIVOTS:]
        sup_pts = swing_lows[-_RECENT_PIVOTS:]

        res_line = _fit_line(res_pts)   # (slope, intercept) for resistance
        sup_line = _fit_line(sup_pts)   # (slope, intercept) for support

        if res_line is None or sup_line is None:
            return _empty

        # Project both lines to the latest bar index
        x_now       = float(len(win) - 1)
        current     = float(win["close"].iloc[-1])
        resistance  = _line_at(*res_line, x_now)
        support     = _line_at(*sup_line, x_now)

        # Guard: support must sit below resistance
        if support >= resistance:
            support, resistance = min(support, resistance), max(support, resistance)

        atr = _atr(win, period=14)
        if atr <= 0 or resistance <= 0:
            return _empty

        channel_width = resistance - support

        # ── Breakout / Breakdown ───────────────────────────────────────────
        breakout  = current > resistance
        breakdown = current < support

        # ── Slope score (support line direction) ──────────────────────────
        # Normalise slope by a 0.1 % of price per bar so it's stock-agnostic
        norm_unit  = current * 0.001
        slope_norm = sup_line[0] / norm_unit if norm_unit > 0 else 0.0
        slope_score = float(np.clip(math.tanh(slope_norm), -1.0, 1.0))

        # ── Trend direction ───────────────────────────────────────────────
        if   sup_line[0] > 0 and res_line[0] > 0:
            trend_dir = "uptrend"
        elif sup_line[0] < 0 and res_line[0] < 0:
            trend_dir = "downtrend"
        else:
            trend_dir = "sideways"

        # ── Channel position score ────────────────────────────────────────
        if breakout:
            excess = (current - resistance) / atr
            channel_score = float(min(1.0, 0.70 + excess * 0.15))
        elif breakdown:
            excess = (support - current) / atr
            channel_score = float(max(-1.0, -(0.70 + excess * 0.15)))
        elif channel_width > 0:
            pos = (current - support) / channel_width   # 0 = at support, 1 = at resistance
            # Upper half of channel in an uptrend = bullish; same position in a
            # downtrend still scores positive but the slope_score will drag it down.
            channel_score = float(np.clip((pos - 0.5) * 0.8, -0.4, 0.4))
        else:
            channel_score = 0.0

        # ── Combined score ────────────────────────────────────────────────
        if breakout or breakdown:
            score = channel_score                          # ±0.70–1.00 from breakout
        else:
            score = 0.55 * slope_score + 0.45 * channel_score

        score = float(np.clip(score, -1.0, 1.0))

        logger.debug(
            "Trendlines  support=%.2f  res=%.2f  close=%.2f  "
            "slope=%+.3f  chan=%+.3f  score=%+.3f  breakout=%s  breakdown=%s",
            support, resistance, current,
            slope_score, channel_score, score, breakout, breakdown,
        )

        return {
            "score":            round(score,        4),
            "support_level":    round(support,       2),
            "resistance_level": round(resistance,    2),
            "trend_dir":        trend_dir,
            "breakout":         breakout,
            "breakdown":        breakdown,
            "slope_score":      round(slope_score,   4),
            "channel_score":    round(channel_score, 4),
        }

    except Exception as exc:
        logger.debug("Trendline computation failed: %s", exc)
        return _empty


# ── Pivot detection ────────────────────────────────────────────────────────────

def _find_swing_highs(highs: pd.Series, n: int) -> list[tuple[int, float]]:
    """Return (bar_index, price) for each local maximum with n bars on each side."""
    pivots: list[tuple[int, float]] = []
    for i in range(n, len(highs) - n):
        val    = highs.iloc[i]
        window = highs.iloc[i - n: i + n + 1]
        # Must be the unique maximum in the window
        if val == window.max() and int((window == val).sum()) == 1:
            pivots.append((i, float(val)))
    return pivots


def _find_swing_lows(lows: pd.Series, n: int) -> list[tuple[int, float]]:
    """Return (bar_index, price) for each local minimum with n bars on each side."""
    pivots: list[tuple[int, float]] = []
    for i in range(n, len(lows) - n):
        val    = lows.iloc[i]
        window = lows.iloc[i - n: i + n + 1]
        if val == window.min() and int((window == val).sum()) == 1:
            pivots.append((i, float(val)))
    return pivots


# ── Line fitting ───────────────────────────────────────────────────────────────

def _fit_line(points: list[tuple[int, float]]) -> tuple[float, float] | None:
    """Least-squares line through pivot (x, price) pairs.  Returns (slope, intercept)."""
    if len(points) < 2:
        return None
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def _line_at(slope: float, intercept: float, x: float) -> float:
    return slope * x + intercept


# ── ATR helper ────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range over the last `period` bars."""
    high        = df["high"]
    low         = df["low"]
    close_prev  = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - close_prev).abs(), (low - close_prev).abs()],
        axis=1,
    ).max(axis=1)
    val = float(tr.rolling(period).mean().iloc[-1])
    return val if not np.isnan(val) else 0.0
