"""
Combined quant + NLP signal.

Merges four alpha sources into a single score that drives autonomous execution:

  NLP (news sentiment)    35%  — directional news flow
  Momentum (12-1 month)   30%  — Jegadeesh-Titman factor
  Mean reversion          20%  — Bollinger/OU oversold/overbought
  Technical composite     15%  — RSI + MACD + EMA crossover

Weights are fixed here; the adaptive engine tunes the buy/sell thresholds
that act on the combined score.
"""
import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Weights when LLM is offline (sum = 1.0)
_WEIGHTS_NO_LLM = {
    "nlp":            0.35,
    "momentum":       0.30,
    "mean_reversion": 0.20,
    "technical":      0.15,
}
# Weights when LLM is online — its signal takes 20%, others scale down
_WEIGHTS_WITH_LLM = {
    "nlp":            0.28,
    "momentum":       0.24,
    "mean_reversion": 0.16,
    "technical":      0.12,
    "llm":            0.20,
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
    direction:            str      # BUY | SELL | HOLD
    confidence:           float    # 0-1
    llm_active:           bool     # True when LLM contributed to the score
    components:           dict = field(default_factory=dict)


async def analyze(ticker: str, nlp_score: float, nlp_confidence: float) -> QuantAnalysis:
    """
    Compute all quant + LLM signals in parallel, combine, and return QuantAnalysis.

    The LLM signal uses Ollama (local model). If Ollama is not running it
    returns 0.0 and the four-factor weights are used instead (safe fallback).
    """
    from app.services.market_data.yfinance_client import get_ohlcv
    from app.services.quant_engine import momentum, mean_reversion, technical
    from app.services.adaptive.adaptive_engine import get_param

    # Fetch prices once; reused across all three quant signal functions
    try:
        df = await asyncio.to_thread(get_ohlcv, ticker, "2y", "1d")
        if df.empty or "close" not in df.columns:
            prices = None
        else:
            prices = df["close"]
    except Exception as e:
        logger.warning(f"Price data fetch failed for {ticker}: {e}")
        prices = None

    if prices is not None and not prices.empty:
        mom_score, mr_score, tech_score = await asyncio.gather(
            asyncio.to_thread(momentum.compute,       prices),
            asyncio.to_thread(mean_reversion.compute, prices),
            asyncio.to_thread(technical.compute,      prices),
        )
    else:
        mom_score = mr_score = tech_score = 0.0

    # ── LLM signal (5th source) ───────────────────────────────────────────
    from app.services.advisor.llm_signal import compute as llm_compute, is_available as llm_alive
    from app.services.adaptive.regime_detector import get_current_regime

    regime      = get_current_regime()
    llm_online  = await llm_alive()

    if llm_online:
        llm_score = await llm_compute(
            ticker=ticker,
            nlp_score=nlp_score,
            momentum_score=mom_score,
            mean_reversion_score=mr_score,
            technical_score=tech_score,
            regime=regime,
        )
        w = _WEIGHTS_WITH_LLM
    else:
        llm_score = 0.0
        w = _WEIGHTS_NO_LLM

    combined = (
        w["nlp"]            * nlp_score
        + w["momentum"]     * mom_score
        + w["mean_reversion"] * mr_score
        + w["technical"]    * tech_score
        + w.get("llm", 0.0) * llm_score
    )
    combined = max(-1.0, min(1.0, combined))

    buy_thr  = get_param("buy_signal_threshold")
    sell_thr = get_param("sell_signal_threshold")

    if combined >= buy_thr:
        direction = "BUY"
    elif combined <= sell_thr:
        direction = "SELL"
    else:
        direction = "HOLD"

    # Confidence rises with source agreement
    active_scores = [nlp_score, mom_score, mr_score, tech_score]
    if llm_online:
        active_scores.append(llm_score)
    n_agree   = sum(1 for s in active_scores if (s > 0) == (combined > 0))
    confidence = min(nlp_confidence + (n_agree / len(active_scores)) * 0.3, 1.0)

    return QuantAnalysis(
        ticker=ticker,
        combined_score=round(combined, 4),
        nlp_score=round(nlp_score, 4),
        momentum_score=round(mom_score, 4),
        mean_reversion_score=round(mr_score, 4),
        technical_score=round(tech_score, 4),
        llm_score=round(llm_score, 4),
        llm_active=llm_online,
        direction=direction,
        confidence=round(confidence, 4),
        components={
            "weights":          w,
            "nlp":              round(nlp_score, 4),
            "momentum":         round(mom_score, 4),
            "mean_reversion":   round(mr_score, 4),
            "technical":        round(tech_score, 4),
            "llm":              round(llm_score, 4),
            "llm_active":       llm_online,
            "buy_threshold":    round(buy_thr, 4),
            "sell_threshold":   round(sell_thr, 4),
        },
    )
