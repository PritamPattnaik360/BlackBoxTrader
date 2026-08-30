"""
Parameter optimizer — reads recent signal outcomes and computes new parameter values.

Adaptation rules:
  - BUY/SELL thresholds tighten when accuracy is poor, loosen when it's strong
  - Risk per trade shrinks when Sharpe is low, grows (slowly) when strong
  - ATR stop multiplier is handled by the regime overlay in adaptive_engine
"""
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

LEARNING_RATE = 0.6          # weight given to new evidence vs current value (higher = faster adaptation)
MIN_OUTCOMES  = 6            # minimum outcomes needed before adapting

# Step sizes below are calibrated for LEARNING_RATE == _BASE_LEARNING_RATE;
# actual steps scale linearly with LEARNING_RATE so it's the single knob
# that speeds up or slows down how fast thresholds/risk react to results.
_BASE_LEARNING_RATE = 0.3


async def compute_new_params(
    session,
    regime: str,
) -> Optional[tuple[dict[str, float], list[tuple[str, str, dict]]]]:
    """
    Returns (new_params, events) or None if there are not enough outcomes.
    Does NOT write to DB — the caller (adaptive_engine) does that.
    """
    from sqlalchemy import select
    from app.models.adaptive import SignalOutcome
    from app.services.adaptive.adaptive_engine import get_param, clamp, DEFAULTS

    result = await session.execute(
        select(SignalOutcome).order_by(SignalOutcome.created_at.desc()).limit(50)
    )
    outcomes = result.scalars().all()

    if len(outcomes) < MIN_OUTCOMES:
        logger.info(f"Only {len(outcomes)} outcomes (need {MIN_OUTCOMES}), skipping optimization")
        return None

    buys  = [o for o in outcomes if o.signal_direction == "BUY"]
    sells = [o for o in outcomes if o.signal_direction == "SELL"]

    buy_acc  = _accuracy(buys)
    sell_acc = _accuracy(sells)

    # Sharpe-like metric on recent outcomes
    pnls = [o.pnl_pct for o in outcomes]
    sharpe = _sharpe(pnls)
    win_rate = sum(1 for o in outcomes if o.was_correct) / len(outcomes)

    new_params: dict[str, float] = {}
    events:     list[tuple[str, str, dict]] = []

    scale = LEARNING_RATE / _BASE_LEARNING_RATE

    # ── BUY threshold ────────────────────────────────────────────────────────
    cur = get_param("buy_signal_threshold")
    if buys:
        if buy_acc < 0.48:
            target = cur + 0.03 * scale
            events.append(("threshold_raised",
                f"BUY threshold {cur:.2f}→{clamp('buy_signal_threshold', target):.2f} "
                f"(accuracy {buy_acc:.0%} < 48%)",
                {"param": "buy_signal_threshold", "before": cur, "after": target, "accuracy": round(buy_acc, 3)}))
        elif buy_acc > 0.65:
            target = cur - 0.01 * scale
            events.append(("threshold_lowered",
                f"BUY threshold {cur:.2f}→{clamp('buy_signal_threshold', target):.2f} "
                f"(accuracy {buy_acc:.0%} > 65%)",
                {"param": "buy_signal_threshold", "before": cur, "after": target, "accuracy": round(buy_acc, 3)}))
        else:
            target = cur
        new_params["buy_signal_threshold"] = clamp("buy_signal_threshold", target)
    else:
        new_params["buy_signal_threshold"] = cur

    # ── SELL threshold ───────────────────────────────────────────────────────
    cur = get_param("sell_signal_threshold")
    if sells:
        if sell_acc < 0.48:
            target = cur - 0.03 * scale   # more negative = fewer SELLs triggered
            events.append(("threshold_raised",
                f"SELL threshold {cur:.2f}→{clamp('sell_signal_threshold', target):.2f} "
                f"(accuracy {sell_acc:.0%} < 48%)",
                {"param": "sell_signal_threshold", "before": cur, "after": target, "accuracy": round(sell_acc, 3)}))
        elif sell_acc > 0.65:
            target = cur + 0.01 * scale   # less negative = more SELLs allowed
            events.append(("threshold_lowered",
                f"SELL threshold {cur:.2f}→{clamp('sell_signal_threshold', target):.2f} "
                f"(accuracy {sell_acc:.0%} > 65%)",
                {"param": "sell_signal_threshold", "before": cur, "after": target, "accuracy": round(sell_acc, 3)}))
        else:
            target = cur
        new_params["sell_signal_threshold"] = clamp("sell_signal_threshold", target)
    else:
        new_params["sell_signal_threshold"] = cur

    # ── Risk per trade ───────────────────────────────────────────────────────
    cur_risk = get_param("risk_per_trade_pct")
    if sharpe < 0.3 or win_rate < 0.40:
        new_risk = cur_risk * (1 - 0.15 * scale)
        events.append(("risk_reduced",
            f"Risk/trade {cur_risk:.3f}→{clamp('risk_per_trade_pct', new_risk):.3f} "
            f"(Sharpe={sharpe:.2f}, win_rate={win_rate:.0%})",
            {"before": round(cur_risk, 5), "after": round(new_risk, 5),
             "sharpe": round(sharpe, 3), "win_rate": round(win_rate, 3)}))
    elif sharpe > 1.5 and win_rate > 0.60:
        ceiling = DEFAULTS["risk_per_trade_pct"] * 2.5
        new_risk = min(cur_risk * (1 + 0.05 * scale), ceiling)
        events.append(("risk_increased",
            f"Risk/trade {cur_risk:.3f}→{clamp('risk_per_trade_pct', new_risk):.3f} "
            f"(Sharpe={sharpe:.2f}, win_rate={win_rate:.0%})",
            {"before": round(cur_risk, 5), "after": round(new_risk, 5),
             "sharpe": round(sharpe, 3), "win_rate": round(win_rate, 3)}))
    else:
        new_risk = cur_risk
    new_params["risk_per_trade_pct"] = clamp("risk_per_trade_pct", new_risk)

    # ATR stop multiplier is managed by regime overlay; carry current value
    new_params["atr_stop_multiplier"] = get_param("atr_stop_multiplier")

    return new_params, events


# ── Helpers ──────────────────────────────────────────────────────────────────

def _accuracy(outcomes) -> float:
    if not outcomes:
        return 0.5
    return sum(1 for o in outcomes if o.was_correct) / len(outcomes)


def _sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(variance) if variance > 0 else 1e-9
    return mean / std
