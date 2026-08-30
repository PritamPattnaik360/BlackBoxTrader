"""
Combined quant + NLP signal.

During market hours, intraday signals (VWAP, ORB, momentum on 5-min bars)
dominate the score. Outside market hours, the daily swing-trading factors
take over.

Intraday weights (market open):
  Intraday composite  36%  — VWAP + ORB + 5-min momentum
  NLP (news)          18%  — directional news flow
  Momentum (12-1 mo)  18%  — Jegadeesh-Titman factor
  Trend lines         10%  — swing pivot support/resistance
  Mean reversion       9%  — Bollinger/OU
  Technical            9%  — RSI + MACD + EMA

Daily weights (market closed):
  NLP                 31%
  Momentum            26%
  Trend lines         12%
  Mean reversion      18%
  Technical           13%

The adaptive engine tunes the buy/sell thresholds that act on the score.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _market_is_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


# Weights when LLM is offline (sum = 1.0)
_WEIGHTS_NO_LLM = {
    "nlp":            0.31,
    "momentum":       0.26,
    "mean_reversion": 0.18,
    "technical":      0.13,
    "trendlines":     0.12,
}
# Weights when LLM is online — its signal takes 20%, others scale down
_WEIGHTS_WITH_LLM = {
    "nlp":            0.25,
    "momentum":       0.21,
    "mean_reversion": 0.14,
    "technical":      0.10,
    "llm":            0.20,
    "trendlines":     0.10,
}
# Intraday weights: VWAP/ORB/momentum on 5-min bars dominate
_WEIGHTS_INTRADAY = {
    "intraday":       0.36,
    "nlp":            0.18,
    "momentum":       0.18,
    "mean_reversion": 0.09,
    "technical":      0.09,
    "trendlines":     0.10,
}
_WEIGHTS_INTRADAY_LLM = {
    "intraday":       0.29,
    "nlp":            0.14,
    "momentum":       0.14,
    "mean_reversion": 0.07,
    "technical":      0.08,
    "llm":            0.20,
    "trendlines":     0.08,
}

WEIGHTS = _WEIGHTS_NO_LLM  # exported for UI display; updated dynamically per call


@dataclass
class QuantAnalysis:
    ticker:               str
    combined_score:       float    # (-1, 1)  — primary signal
    nlp_score:            float
    momentum_score:       float
    mean_reversion_score: float
    technical_score:      float
    llm_score:            float    # 0.0 when Ollama not running
    intraday_score:       float    # 0.0 when market closed
    trendline_score:      float    # swing pivot support/resistance signal
    direction:            str      # BUY | SELL | HOLD
    confidence:           float    # 0-1
    llm_active:           bool
    intraday_active:      bool
    components:           dict = field(default_factory=dict)


async def analyze(ticker: str, nlp_score: float, nlp_confidence: float) -> QuantAnalysis:
    """
    Compute all quant + LLM + intraday signals in parallel, combine, and return.

    During market hours intraday signals (VWAP/ORB/5-min momentum) dominate.
    Outside market hours the daily swing-trading factors are used instead.
    """
    from app.services.market_data.yfinance_client import get_ohlcv, get_intraday_5m
    from app.services.quant_engine import momentum, mean_reversion, technical
    from app.services.quant_engine.intraday import compute_all as intraday_compute
    from app.services.adaptive.adaptive_engine import get_param

    market_open = _market_is_open()

    # ── Daily prices (always fetched for swing factors) ───────────────────
    try:
        df_daily = await asyncio.to_thread(get_ohlcv, ticker, "2y", "1d")
        prices = df_daily["close"] if not df_daily.empty and "close" in df_daily.columns else None
        avg_daily_vol = float(df_daily["volume"].mean()) if prices is not None and "volume" in df_daily.columns else 0.0
    except Exception as e:
        logger.warning(f"Daily price fetch failed for {ticker}: {e}")
        prices = None
        avg_daily_vol = 0.0

    if prices is not None and not prices.empty:
        from app.services.quant_engine import trendlines as trendlines_mod
        mom_score, mr_score, tech_score, tl_result = await asyncio.gather(
            asyncio.to_thread(momentum.compute,          prices),
            asyncio.to_thread(mean_reversion.compute,    prices),
            asyncio.to_thread(technical.compute,         prices),
            asyncio.to_thread(trendlines_mod.compute,    df_daily, 5, 90),
        )
    else:
        mom_score = mr_score = tech_score = 0.0
        tl_result = {"score": 0.0, "support_level": 0.0, "resistance_level": 0.0,
                     "trend_dir": "sideways", "breakout": False, "breakdown": False,
                     "slope_score": 0.0, "channel_score": 0.0}
    trendline_score = tl_result["score"]

    # ── Intraday signals (market hours only) ─────────────────────────────
    intraday_result = {"combined": 0.0, "vwap": 0.0, "orb": 0.0, "intraday_momentum": 0.0, "rvol": 1.0}
    if market_open:
        try:
            df_5m = await asyncio.to_thread(get_intraday_5m, ticker)
            intraday_result = intraday_compute(df_5m, avg_daily_vol)
        except Exception as e:
            logger.warning(f"Intraday data fetch failed for {ticker}: {e}")
    intraday_score  = intraday_result["combined"]
    intraday_active = market_open and intraday_score != 0.0

    # ── LLM signal ────────────────────────────────────────────────────────
    from app.services.advisor.llm_signal import compute as llm_compute, is_available as llm_alive
    from app.services.adaptive.regime_detector import get_current_regime

    regime     = get_current_regime()
    llm_online = await llm_alive()

    if llm_online:
        llm_score = await llm_compute(
            ticker=ticker,
            nlp_score=nlp_score,
            momentum_score=mom_score,
            mean_reversion_score=mr_score,
            technical_score=tech_score,
            regime=regime,
            trendline_data=tl_result,
        )
    else:
        llm_score = 0.0

    # ── Combine ───────────────────────────────────────────────────────────
    if market_open:
        w = _WEIGHTS_INTRADAY_LLM if llm_online else _WEIGHTS_INTRADAY
        combined = (
            w["intraday"]           * intraday_score
            + w["nlp"]              * nlp_score
            + w["momentum"]         * mom_score
            + w["mean_reversion"]   * mr_score
            + w["technical"]        * tech_score
            + w["trendlines"]       * trendline_score
            + w.get("llm", 0.0)    * llm_score
        )
    else:
        w = _WEIGHTS_WITH_LLM if llm_online else _WEIGHTS_NO_LLM
        combined = (
            w["nlp"]                * nlp_score
            + w["momentum"]         * mom_score
            + w["mean_reversion"]   * mr_score
            + w["technical"]        * tech_score
            + w["trendlines"]       * trendline_score
            + w.get("llm", 0.0)    * llm_score
        )

    combined = max(-1.0, min(1.0, combined))

    buy_thr  = get_param("buy_signal_threshold")
    sell_thr = get_param("sell_signal_threshold")

    # Breakout mode: a confirmed high-volume intraday move (RVOL + ORB/VWAP/
    # momentum agreeing with the overall score) discounts the threshold needed
    # to act on it, instead of requiring the same bar the system uses on quiet
    # tape. This is the per-ticker complement to the regime-level breakout
    # overlay in adaptive_engine — it reacts to *this* ticker actually moving,
    # not just the macro regime.
    from app.services.quant_engine.intraday import RVOL_THRESHOLD
    BREAKOUT_THRESHOLD_DISCOUNT = 0.7
    breakout_confirmed = (
        intraday_active
        and intraday_result["rvol"] >= RVOL_THRESHOLD
        and (intraday_score > 0) == (combined > 0)
    )
    if breakout_confirmed:
        buy_thr  *= BREAKOUT_THRESHOLD_DISCOUNT
        sell_thr *= BREAKOUT_THRESHOLD_DISCOUNT

    if combined >= buy_thr:
        direction = "BUY"
    elif combined <= sell_thr:
        direction = "SELL"
    else:
        direction = "HOLD"

    active_scores = [nlp_score, mom_score, mr_score, tech_score]
    if intraday_active:
        active_scores.append(intraday_score)
    if llm_online:
        active_scores.append(llm_score)
    if trendline_score != 0.0:
        active_scores.append(trendline_score)
    n_agree    = sum(1 for s in active_scores if (s > 0) == (combined > 0))
    confidence = min(nlp_confidence + (n_agree / len(active_scores)) * 0.3, 1.0)

    return QuantAnalysis(
        ticker=ticker,
        combined_score=round(combined, 4),
        nlp_score=round(nlp_score, 4),
        momentum_score=round(mom_score, 4),
        mean_reversion_score=round(mr_score, 4),
        technical_score=round(tech_score, 4),
        llm_score=round(llm_score, 4),
        intraday_score=round(intraday_score, 4),
        trendline_score=round(trendline_score, 4),
        llm_active=llm_online,
        intraday_active=intraday_active,
        direction=direction,
        confidence=round(confidence, 4),
        components={
            "weights":                  w,
            "mode":                     "intraday" if market_open else "daily",
            "nlp":                      round(nlp_score, 4),
            "momentum":                 round(mom_score, 4),
            "mean_reversion":           round(mr_score, 4),
            "technical":                round(tech_score, 4),
            "llm":                      round(llm_score, 4),
            "llm_active":               llm_online,
            "intraday":                 round(intraday_score, 4),
            "intraday_vwap":            round(intraday_result["vwap"], 4),
            "intraday_orb":             round(intraday_result["orb"], 4),
            "intraday_momentum":        round(intraday_result["intraday_momentum"], 4),
            "rvol":                     round(intraday_result["rvol"], 3),
            "trendlines":               round(trendline_score, 4),
            "trendline_support":        tl_result["support_level"],
            "trendline_resistance":     tl_result["resistance_level"],
            "trendline_dir":            tl_result["trend_dir"],
            "trendline_breakout":       tl_result["breakout"],
            "trendline_breakdown":      tl_result["breakdown"],
            "buy_threshold":            round(buy_thr, 4),
            "sell_threshold":           round(sell_thr, 4),
            "breakout_mode":            breakout_confirmed,
        },
    )
