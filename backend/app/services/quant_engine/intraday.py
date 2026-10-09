"""
Intraday day trading signals on 5-minute bars.

Three patterns:
  VWAP deviation      — price vs. session VWAP (40%)
  Opening Range Breakout (ORB) — first 30-min high/low breakout (35%)
  Intraday momentum   — 5-bar ROC on 5-min closes (25%)

Relative volume (RVOL) acts as a confidence amplifier: when the stock is
trading at >1.5× its typical volume it's "in play" and scores are boosted.
"""
import math
import logging
import pandas as pd

logger = logging.getLogger(__name__)

ORB_BARS = 6          # 6 × 5 min = first 30 minutes
MOM_BARS = 5          # 5 × 5 min = last 25 minutes of momentum
RVOL_THRESHOLD = 1.5  # amplify signals when volume is this high


def compute_all(df: pd.DataFrame, avg_daily_vol: float = 0.0, bias: str = "neutral") -> dict:
    """
    Args:
        df: 5-minute OHLCV bars for the current session
            (columns: open, high, low, close, volume).
        avg_daily_vol: 3-month average daily volume from daily data
                       (used for RVOL; pass 0 to skip amplification).
        bias: market bias ("bull" | "neutral" | "bear") — picks the playbook:
              bull    → trend/breakout following (ORB gets the biggest weight)
              neutral → original VWAP/ORB/momentum mix
              bear    → breakouts fail more often, so fade washed-out dips instead
    Returns dict with keys: vwap, orb, intraday_momentum, fade, rvol, combined.
    """
    empty = {"vwap": 0.0, "orb": 0.0, "intraday_momentum": 0.0, "fade": 0.0, "rvol": 1.0, "combined": 0.0}
    if df is None or df.empty or len(df) < 3:
        return empty

    vwap_score = _vwap_signal(df)
    orb_score  = _orb_signal(df)
    mom_score  = _intraday_momentum(df)
    fade_score = _fade_signal(df)
    rvol       = _relative_volume(df, avg_daily_vol)

    if bias == "bull":
        combined = 0.30 * vwap_score + 0.40 * orb_score + 0.30 * mom_score
    elif bias == "bear":
        combined = (0.20 * vwap_score + 0.20 * orb_score
                    + 0.15 * mom_score + 0.45 * fade_score)
    else:
        combined = 0.40 * vwap_score + 0.35 * orb_score + 0.25 * mom_score

    # Amplify when high relative volume (stock is actively traded)
    if rvol >= RVOL_THRESHOLD:
        boost = min(rvol / RVOL_THRESHOLD, 1.5)
        combined *= boost

    combined = max(-1.0, min(1.0, combined))

    logger.debug(
        f"Intraday → vwap={vwap_score:+.3f} orb={orb_score:+.3f} "
        f"mom={mom_score:+.3f} rvol={rvol:.2f}x → {combined:+.3f}"
    )

    return {
        "vwap":              round(vwap_score, 4),
        "orb":               round(orb_score,  4),
        "intraday_momentum": round(mom_score,  4),
        "fade":              round(fade_score, 4),
        "rvol":              round(rvol,        3),
        "combined":          round(combined,    4),
    }


# ── Component signals ─────────────────────────────────────────────────────────

def _vwap_signal(df: pd.DataFrame) -> float:
    """
    VWAP = Σ(typical_price × volume) / Σ(volume) for the session.
    Score = tanh of price deviation from VWAP (%).
    Price > VWAP → positive (bullish), < VWAP → negative (bearish).
    """
    try:
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        vwap = (typical * df["volume"]).sum() / df["volume"].replace(0, 1).sum()
        current = float(df["close"].iloc[-1])
        if vwap <= 0:
            return 0.0
        deviation = (current - vwap) / vwap
        # 1% away from VWAP → ~0.50 score; 2% → ~0.76; 3% → ~0.90
        return max(-1.0, min(1.0, math.tanh(deviation * 30.0)))
    except Exception as e:
        logger.debug(f"VWAP signal error: {e}")
        return 0.0


def _orb_signal(df: pd.DataFrame) -> float:
    """
    Opening Range Breakout: high/low of first 30 minutes (ORB_BARS × 5 min).
    Breakout above ORH → +0.7 to +1.0 (scaled by distance).
    Breakdown below ORL → -0.7 to -1.0.
    Inside range → -0.3 to +0.3 (lean toward midpoint position).
    Returns 0.0 if opening range hasn't fully formed yet.
    """
    try:
        if len(df) < ORB_BARS:
            return 0.0

        or_bars = df.iloc[:ORB_BARS]
        orh = float(or_bars["high"].max())
        orl = float(or_bars["low"].min())
        or_range = orh - orl
        if or_range <= 0:
            return 0.0

        current = float(df["close"].iloc[-1])

        if current > orh:
            excess = (current - orh) / or_range
            return min(1.0, 0.7 + excess * 0.6)
        elif current < orl:
            excess = (orl - current) / or_range
            return max(-1.0, -(0.7 + excess * 0.6))
        else:
            midpoint = (orh + orl) / 2.0
            return (current - midpoint) / (or_range / 2.0) * 0.3
    except Exception as e:
        logger.debug(f"ORB signal error: {e}")
        return 0.0


def _intraday_momentum(df: pd.DataFrame) -> float:
    """5-bar rate of change on 5-min closes (= last 25 minutes of price action)."""
    try:
        closes = df["close"].dropna()
        if len(closes) < MOM_BARS + 1:
            return 0.0
        past = float(closes.iloc[-(MOM_BARS + 1)])
        now  = float(closes.iloc[-1])
        if past <= 0:
            return 0.0
        roc = (now - past) / past
        # 0.5% move in 25 min → ~0.50; 1% → ~0.76; 2% → ~0.96
        return max(-1.0, min(1.0, math.tanh(roc * 60.0)))
    except Exception as e:
        logger.debug(f"Intraday momentum error: {e}")
        return 0.0


def _fade_signal(df: pd.DataFrame, period: int = 7) -> float:
    """
    Intraday mean-reversion (used in bearish markets): 5-min RSI(7) washed out
    AND price stretched below VWAP → bounce candidate (+); the mirror image
    (overbought and stretched above VWAP) → fade the rip (−, i.e. exit signal).
    Requires both conditions so a plain downtrend isn't mistaken for a bounce.
    """
    try:
        closes = df["close"].dropna()
        if len(closes) < period + 3:
            return 0.0
        delta = closes.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss = (-delta).clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        rsi = float(100 - 100 / (1 + gain.iloc[-1] / max(loss.iloc[-1], 1e-9)))

        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        vwap = (typical * df["volume"]).sum() / max(df["volume"].sum(), 1)
        dev = (float(closes.iloc[-1]) - vwap) / vwap if vwap > 0 else 0.0

        if rsi < 30 and dev < -0.004:
            return min(1.0, (30 - rsi) / 20 + abs(dev) * 40)
        if rsi > 70 and dev > 0.004:
            return -min(1.0, (rsi - 70) / 20 + abs(dev) * 40)
        return 0.0
    except Exception as e:
        logger.debug(f"Fade signal error: {e}")
        return 0.0


def _relative_volume(df: pd.DataFrame, avg_daily_vol: float) -> float:
    """
    RVOL = today's cumulative volume / expected volume at this point in the day.
    Expected = avg_daily_vol × (bars_so_far / total_trading_bars_per_day).
    Returns 1.0 when avg_daily_vol is unknown.
    """
    try:
        if avg_daily_vol <= 0:
            return 1.0
        trading_bars_per_day = 78   # 6.5 hours × 12 bars/hour
        bars_elapsed = len(df)
        expected = avg_daily_vol * (bars_elapsed / trading_bars_per_day)
        if expected <= 0:
            return 1.0
        today_vol = float(df["volume"].sum())
        return today_vol / expected
    except Exception:
        return 1.0
