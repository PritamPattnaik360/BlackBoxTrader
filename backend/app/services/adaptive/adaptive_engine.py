"""
Adaptive learning engine — state hub for all self-tuning parameters.

Other modules call get_param(name) to read the current adaptive value instead
of using hardcoded constants. Parameters evolve as trade outcomes accumulate.
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Defaults & bounds ────────────────────────────────────────────────────────

DEFAULTS: dict[str, float] = {
    "buy_signal_threshold": 0.3,
    "sell_signal_threshold": -0.3,
    "risk_per_trade_pct": 0.01,
    "atr_stop_multiplier": 2.0,
}

BOUNDS: dict[str, tuple[float, float]] = {
    "buy_signal_threshold":  (0.10, 0.60),
    "sell_signal_threshold": (-0.60, -0.10),
    "risk_per_trade_pct":    (0.005, 0.035),
    "atr_stop_multiplier":   (1.2, 4.0),
}

# ── In-memory state ──────────────────────────────────────────────────────────

_params: dict[str, float] = dict(DEFAULTS)
_regime: str = "normal"
_current_generation: int = 0
_outcomes_since_last_opt: int = 0

OPTIMIZE_AFTER_N_OUTCOMES = 10   # auto-trigger every N closed trades


# ── Public accessors ─────────────────────────────────────────────────────────

def get_param(name: str) -> float:
    return _params.get(name, DEFAULTS[name])


def get_regime() -> str:
    return _regime


def set_regime(regime: str) -> None:
    global _regime
    _regime = regime


def clamp(name: str, value: float) -> float:
    lo, hi = BOUNDS.get(name, (-999.0, 999.0))
    return max(lo, min(hi, value))


def _set_params(new_params: dict[str, float]) -> None:
    _params.update(new_params)


# ── DB bootstrap ─────────────────────────────────────────────────────────────

async def load_from_db(session) -> None:
    """Restore last tuned values from DB on startup."""
    global _current_generation
    from sqlalchemy import select
    from app.models.adaptive import AdaptiveParam

    result = await session.execute(
        select(AdaptiveParam).order_by(AdaptiveParam.generation.desc())
    )
    rows = result.scalars().all()

    seen: set[str] = set()
    for row in rows:
        if row.name not in seen:
            _params[row.name] = row.value
            _current_generation = max(_current_generation, row.generation)
            seen.add(row.name)

    logger.info(
        f"Adaptive params loaded (gen {_current_generation}): "
        + ", ".join(f"{k}={v:.4f}" for k, v in _params.items())
    )


# ── Main optimization entry point ────────────────────────────────────────────

async def run_optimization(session) -> None:
    """
    Full optimization pass: detect regime, tune parameters from outcomes,
    persist to DB, hot-reload into memory.
    """
    global _current_generation

    logger.info("Running adaptive optimization...")

    # 1. Regime detection (blocking yfinance call; run in thread)
    from app.services.adaptive import regime_detector
    try:
        new_regime = await asyncio.to_thread(regime_detector.detect_regime)
    except Exception as e:
        logger.warning(f"Regime detection failed: {e}")
        new_regime = _regime

    old_regime = _regime
    set_regime(new_regime)

    # 2. Parameter optimization from closed trade outcomes
    from app.services.adaptive import parameter_optimizer
    result = await parameter_optimizer.compute_new_params(session, new_regime)

    if result is None:
        return   # not enough outcomes yet

    new_params, events = result

    # Apply regime overlay on top of outcome-tuned params
    if new_regime != old_regime:
        events.append((
            "regime_change",
            f"Market regime changed {old_regime} → {new_regime}",
            {"from": old_regime, "to": new_regime},
        ))
        _apply_regime_overlay(new_params, new_regime)

    # 3. Persist to DB
    _current_generation += 1
    new_gen = _current_generation

    from app.models.adaptive import AdaptiveParam, AdaptiveEvent
    for name, value in new_params.items():
        prev = get_param(name)
        session.add(AdaptiveParam(
            name=name,
            value=value,
            previous_value=prev,
            reason=f"Gen {new_gen}",
            generation=new_gen,
        ))

    for ev_type, ev_desc, ev_data in events:
        session.add(AdaptiveEvent(
            event_type=ev_type,
            description=ev_desc,
            data=ev_data,
        ))

    await session.commit()

    # 4. Hot-reload
    _set_params(new_params)
    logger.info(
        f"Adaptive params updated (gen {new_gen}, regime={new_regime}): "
        + ", ".join(f"{k}={v:.4f}" for k, v in new_params.items())
    )


def _apply_regime_overlay(params: dict[str, float], regime: str) -> None:
    """Shift parameters according to market regime."""
    if regime == "high_volatility":
        # Elevated vol with NO confirmed trend = choppy/whipsaw conditions.
        # Stay defensive: wider stops, more conservative thresholds.
        params["atr_stop_multiplier"] = clamp("atr_stop_multiplier", params.get("atr_stop_multiplier", DEFAULTS["atr_stop_multiplier"]) + 0.5)
        params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) + 0.04)
        params["sell_signal_threshold"] = clamp("sell_signal_threshold", params.get("sell_signal_threshold", DEFAULTS["sell_signal_threshold"]) - 0.04)
    elif regime in ("volatile_trending_up", "volatile_trending_down"):
        # Breakout mode: elevated vol WITH a confirmed directional trend.
        # This used to be lumped into high_volatility and dampened like
        # chop — but a big confirmed move is exactly when the system
        # should lean in, not sit out. Stops stay wide (real trends need
        # room to breathe) while thresholds loosen in the trend direction
        # so signals in that direction actually get acted on.
        params["atr_stop_multiplier"] = clamp("atr_stop_multiplier", params.get("atr_stop_multiplier", DEFAULTS["atr_stop_multiplier"]) + 0.3)
        if regime == "volatile_trending_up":
            params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) - 0.06)
            params["sell_signal_threshold"] = clamp("sell_signal_threshold", params.get("sell_signal_threshold", DEFAULTS["sell_signal_threshold"]) - 0.03)
        else:
            params["sell_signal_threshold"] = clamp("sell_signal_threshold", params.get("sell_signal_threshold", DEFAULTS["sell_signal_threshold"]) + 0.06)
            params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) + 0.03)
    elif regime == "low_volatility":
        # Tighter stops, allow more signals
        params["atr_stop_multiplier"] = clamp("atr_stop_multiplier", params.get("atr_stop_multiplier", DEFAULTS["atr_stop_multiplier"]) - 0.2)
        params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) - 0.02)
    elif regime == "trending_up":
        # Trust BUY signals more; be cautious with SELL
        params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) - 0.02)
        params["sell_signal_threshold"] = clamp("sell_signal_threshold", params.get("sell_signal_threshold", DEFAULTS["sell_signal_threshold"]) - 0.02)
    elif regime == "trending_down":
        params["sell_signal_threshold"] = clamp("sell_signal_threshold", params.get("sell_signal_threshold", DEFAULTS["sell_signal_threshold"]) + 0.02)
        params["buy_signal_threshold"] = clamp("buy_signal_threshold", params.get("buy_signal_threshold", DEFAULTS["buy_signal_threshold"]) + 0.02)


async def reset_to_defaults(session) -> None:
    """Reset all parameters to factory defaults and log the event."""
    global _current_generation
    _params.update(DEFAULTS)
    _current_generation += 1
    from app.models.adaptive import AdaptiveParam, AdaptiveEvent
    for name, value in DEFAULTS.items():
        session.add(AdaptiveParam(
            name=name,
            value=value,
            previous_value=None,
            reason="Manual reset to defaults",
            generation=_current_generation,
        ))
    session.add(AdaptiveEvent(
        event_type="reset",
        description="All adaptive parameters reset to factory defaults",
        data=DEFAULTS,
    ))
    await session.commit()
    logger.info("Adaptive parameters reset to defaults")
