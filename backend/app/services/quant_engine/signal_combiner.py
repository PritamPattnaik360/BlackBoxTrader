"""
Combined quant + NLP signal.

The algorithm mix depends on two things:
  * Market bias (bull / neutral / bear, from SPY trend + VIX) — picks the weight
    table, threshold shifts, position-size multiplier and stop width. See
    app.services.strategy.market_bias.PROFILES for the exact numbers.
  * Market hours — during the session the intraday composite (VWAP / opening
    range breakout / 5-min momentum, or the bounce-fade in bear markets) is
    included; outside it the daily swing factors take over.

When the local LLM is online it takes a 20% slice and the rest scale down.
The adaptive engine tunes the base buy/sell thresholds the profile shifts.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.services.strategy import market_bias

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Day-trade entries are only taken after the opening range has formed and
# before the late-session liquidity drain.
DAY_TRADE_START = dtime(10, 0)
DAY_TRADE_END   = dtime(15, 30)
DAY_TRADE_MIN_INTRADAY_SCORE = 0.35
BREAKOUT_THRESHOLD_DISCOUNT = 0.7   # thresholds shrink to this fraction on a volume-confirmed breakout


def _market_is_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


def _in_day_trade_window() -> bool:
    return DAY_TRADE_START <= datetime.now(ET).time() <= DAY_TRADE_END


WEIGHTS = market_bias.PROFILES["neutral"].daily_weights  # exported for UI display


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
    bias:                 str = "neutral"   # bull | neutral | bear
    trade_style:          str = "swing"     # swing | day
    size_mult:            float = 1.0       # profile position-size multiplier
    stop_mult_adj:        float = 0.0       # profile ATR-stop adjustment
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
    bias        = market_bias.get_bias()
    profile     = market_bias.get_profile(bias)

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
    intraday_result = {"combined": 0.0, "vwap": 0.0, "orb": 0.0, "intraday_momentum": 0.0, "fade": 0.0, "rvol": 1.0}
    if market_open:
        try:
            df_5m = await asyncio.to_thread(get_intraday_5m, ticker)
            intraday_result = intraday_compute(df_5m, avg_daily_vol, bias)
        except Exception as e:
            logger.warning(f"Intraday data fetch failed for {ticker}: {e}")
    intraday_score  = intraday_result["combined"]
    intraday_active = market_open and intraday_score != 0.0

    # ── LLM signal ────────────────────────────────────────────────────────
    from app.services.advisor.llm_signal import compute as llm_compute, is_available as llm_alive
    from app.services.adaptive.regime_detector import get_current_regime

    regime     = get_current_regime()
    # The LLM trading signal only runs while the US market is open; outside the
    # session the daily factors are used alone (no point burning inference on
    # signals that can't be traded until the next open).
    llm_online = market_open and await llm_alive()

    def _blend(w: dict, llm: float) -> float:
        if market_open:
            total = w["intraday"] * intraday_score
        else:
            total = 0.0
        return (total
                + w["nlp"]            * nlp_score
                + w["momentum"]       * mom_score
                + w["mean_reversion"] * mr_score
                + w["technical"]      * tech_score
                + w["trendlines"]     * trendline_score
                + w.get("llm", 0.0)   * llm)

    base = profile.intraday_weights if market_open else profile.daily_weights

    # Adaptive base thresholds, shifted by the market-bias profile
    # (bull: easier BUY / harder SELL; bear: much harder BUY / easier exit).
    buy_thr  = min(0.70, max(0.10, get_param("buy_signal_threshold") + profile.buy_thr_adj))
    sell_thr = min(-0.08, max(-0.60, get_param("sell_signal_threshold") + profile.sell_thr_adj))

    # LLM inference is by far the slowest step (~15s/ticker). With the LLM online,
    # combined = 0.8·pre + 0.2·llm with llm ∈ [-1, 1], so it can only change the
    # decision if that range reaches a threshold. Otherwise skip it — the BUY /
    # SELL / HOLD outcome is identical and a 25-35 ticker scan fits its interval.
    if llm_online:
        pre = _blend(base, 0.0)
        lo, hi = 0.8 * pre - 0.2, 0.8 * pre + 0.2
        certain_hold = hi < BREAKOUT_THRESHOLD_DISCOUNT * buy_thr and lo > BREAKOUT_THRESHOLD_DISCOUNT * sell_thr
        if certain_hold or lo >= buy_thr or hi <= sell_thr:
            llm_online = False

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
    w = market_bias.with_llm(base) if llm_online else base
    combined = _blend(w, llm_score)

    combined = max(-1.0, min(1.0, combined))

    # Breakout mode: a confirmed high-volume intraday move (RVOL + ORB/VWAP/
    # momentum agreeing with the overall score) discounts the threshold needed
    # to act on it, instead of requiring the same bar the system uses on quiet
    # tape. This is the per-ticker complement to the regime-level breakout
    # overlay in adaptive_engine — it reacts to *this* ticker actually moving,
    # not just the macro regime.
    from app.services.quant_engine.intraday import RVOL_THRESHOLD
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

    # Day trade = a strong intraday setup inside the trading window. Bull markets
    # need a volume-confirmed breakout; in bear markets bounce-fades qualify without
    # it (they're short-lived by nature). Everything else is a swing position.
    trade_style = "swing"
    if direction == "BUY" and intraday_active and _in_day_trade_window():
        from app.config import settings
        if settings.day_trade_only:
            # Day-trade-only: every BUY with a live, positive intraday read is a same-day trade
            if intraday_score > 0:
                trade_style = "day"
        elif (intraday_score >= DAY_TRADE_MIN_INTRADAY_SCORE
              and (breakout_confirmed or bias == "bear")):
            trade_style = "day"

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
        bias=bias,
        trade_style=trade_style,
        size_mult=profile.size_mult,
        stop_mult_adj=profile.stop_mult_adj,
        direction=direction,
        confidence=round(confidence, 4),
        components={
            "weights":                  w,
            "mode":                     "intraday" if market_open else "daily",
            "bias":                     bias,
            "trade_style":              trade_style,
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
            "intraday_fade":            round(intraday_result.get("fade", 0.0), 4),
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
