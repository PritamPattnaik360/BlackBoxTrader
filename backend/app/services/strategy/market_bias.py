"""
Market bias (bull / neutral / bear) and the strategy profile that goes with it.

The bias is derived from the S&P 500 (SPY) trend plus VIX, and decides *which
algorithm mix* the signal combiner uses:

  bull     — trend-following: momentum, trend lines and breakouts dominate,
             dips are bought, full position size.
  neutral  — balanced mix (the original weights), 80% size.
  bear     — defensive: mean-reversion / oversold bounces and news dominate,
             momentum is down-weighted, BUY needs a much higher score, SELL
             (= exit) triggers sooner, half size, tighter stops.

There is still no short-selling: a bearish view means staying out, exiting
early, or (if ENABLE_OPTIONS_TRADING) buying puts.
"""
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BIAS_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class Profile:
    name:           str
    label:          str
    daily_weights:  dict
    intraday_weights: dict
    buy_thr_adj:    float   # added to the adaptive BUY threshold
    sell_thr_adj:    float   # added to the adaptive SELL threshold (negative number)
    size_mult:      float   # multiplies risk-per-trade
    stop_mult_adj:  float   # added to the ATR stop multiplier
    description:    str


PROFILES: dict[str, Profile] = {
    "bull": Profile(
        name="bull", label="Bullish — trend following",
        daily_weights={"nlp": 0.20, "momentum": 0.32, "trendlines": 0.18,
                       "technical": 0.18, "mean_reversion": 0.12},
        intraday_weights={"intraday": 0.40, "nlp": 0.14, "momentum": 0.16,
                          "trendlines": 0.12, "technical": 0.10, "mean_reversion": 0.08},
        buy_thr_adj=-0.05, sell_thr_adj=-0.05, size_mult=1.0, stop_mult_adj=0.0,
        description="Momentum + trend lines + opening-range breakouts. Buys strength and dips, "
                    "lets winners run (SELL needs a stronger signal).",
    ),
    "neutral": Profile(
        name="neutral", label="Neutral — balanced",
        daily_weights={"nlp": 0.31, "momentum": 0.26, "mean_reversion": 0.18,
                       "technical": 0.13, "trendlines": 0.12},
        intraday_weights={"intraday": 0.36, "nlp": 0.18, "momentum": 0.18,
                          "mean_reversion": 0.09, "technical": 0.09, "trendlines": 0.10},
        buy_thr_adj=0.0, sell_thr_adj=0.0, size_mult=0.8, stop_mult_adj=0.0,
        description="Original balanced mix of news, momentum and mean-reversion.",
    ),
    "bear": Profile(
        name="bear", label="Bearish — defensive / bounce",
        daily_weights={"mean_reversion": 0.30, "nlp": 0.25, "trendlines": 0.18,
                       "technical": 0.15, "momentum": 0.12},
        intraday_weights={"intraday": 0.36, "nlp": 0.20, "mean_reversion": 0.16,
                          "trendlines": 0.12, "technical": 0.08, "momentum": 0.08},
        buy_thr_adj=0.10, sell_thr_adj=0.08, size_mult=0.5, stop_mult_adj=-0.4,
        description="Oversold-bounce / mean-reversion focus, news-driven. High bar to buy, "
                    "exits trigger early, half size, tighter stops, intraday fades instead of breakouts.",
    ),
}

_cache: dict = {"ts": 0.0, "data": None}


def _neutral_context(reason: str) -> dict:
    return {"bias": "neutral", "score": 0, "vix": None, "spy_price": None,
            "spy_vs_200dma_pct": None, "spy_vs_50dma_pct": None,
            "ma50_above_ma200": None, "reason": reason}


def compute_bias() -> dict:
    """Blocking (yfinance). Score = SPY trend votes + VIX votes; ≥2 bull, ≤-2 bear."""
    try:
        import pandas as pd
        import yfinance as yf

        raw = yf.download(["SPY", "^VIX"], period="1y", progress=False, auto_adjust=True)
        close = raw["Close"]
        if not isinstance(close, pd.DataFrame) or "SPY" not in close:
            return _neutral_context("SPY data unavailable")
        spy = close["SPY"].dropna()
        if len(spy) < 60:
            return _neutral_context("not enough SPY history")
        vix_s = close["^VIX"].dropna() if "^VIX" in close else pd.Series(dtype=float)

        price = float(spy.iloc[-1])
        ma50  = float(spy.tail(50).mean())
        ma200 = float(spy.tail(200).mean()) if len(spy) >= 200 else float(spy.mean())
        vix   = float(vix_s.iloc[-1]) if len(vix_s) else None
        ret_20d = price / float(spy.iloc[-21]) - 1 if len(spy) > 21 else 0.0

        score = 0
        score += 1 if price > ma200 else -1
        score += 1 if ma50 > ma200 else -1
        score += 1 if price > ma50 else -1
        if ret_20d > 0.02:
            score += 1
        elif ret_20d < -0.04:
            score -= 1
        if vix is not None:
            if vix < 18:
                score += 1
            elif vix > 30:
                score -= 2
            elif vix > 24:
                score -= 1

        bias = "bull" if score >= 2 else "bear" if score <= -2 else "neutral"
        return {
            "bias": bias, "score": score,
            "vix": round(vix, 2) if vix is not None else None,
            "spy_price": round(price, 2),
            "spy_vs_200dma_pct": round((price / ma200 - 1) * 100, 2),
            "spy_vs_50dma_pct": round((price / ma50 - 1) * 100, 2),
            "ret_20d_pct": round(ret_20d * 100, 2),
            "ma50_above_ma200": ma50 > ma200,
            "reason": "SPY trend + VIX",
        }
    except Exception as e:
        logger.warning(f"Market bias detection failed, defaulting to neutral: {e}")
        return _neutral_context(f"error: {e}")


def refresh_bias(force: bool = False) -> dict:
    """Blocking. Recompute if the cached value is older than the TTL."""
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < BIAS_TTL_SECONDS:
        return _cache["data"]
    data = compute_bias()
    prev = _cache["data"]["bias"] if _cache["data"] else None
    _cache.update(ts=now, data=data)
    if prev != data["bias"]:
        logger.info(f"Market bias: {prev} → {data['bias']} (score {data['score']}, VIX {data.get('vix')})")
    return data


def get_bias() -> str:
    """Non-blocking: last computed bias, 'neutral' before the first refresh."""
    data = _cache["data"]
    return data["bias"] if data else "neutral"


def get_context() -> dict:
    return _cache["data"] or _neutral_context("not yet computed")


def get_profile(bias: str | None = None) -> Profile:
    return PROFILES.get(bias or get_bias(), PROFILES["neutral"])


def with_llm(weights: dict, llm_share: float = 0.20) -> dict:
    """Carve an LLM slice out of a weight set, scaling the rest so it still sums to 1."""
    out = {k: v * (1 - llm_share) for k, v in weights.items()}
    out["llm"] = llm_share
    return out
