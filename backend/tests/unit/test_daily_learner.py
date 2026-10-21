import math

import numpy as np
import pandas as pd

from app.services.adaptive import daily_learner as dl
from app.services.strategy.market_bias import PROFILES


def test_rank_ic_detects_signal_and_ignores_noise():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=300))
    good = x * 0.01 + pd.Series(rng.normal(scale=0.01, size=300))
    noise = pd.Series(rng.normal(size=300))
    assert dl.rank_ic(x, good) > 0.4
    assert abs(dl.rank_ic(x, noise)) < 0.2
    assert dl.rank_ic(pd.Series([0.0] * 100), good.iloc[:100]) is None   # constant -> undefined


def test_update_weights_shifts_toward_predictive_components_and_stays_normalised():
    default = PROFILES["bull"].daily_weights
    new = dl.update_weights(default, default, {"momentum": 0.30, "mean_reversion": -0.30})
    assert math.isclose(sum(new.values()), 1.0, abs_tol=1e-3)
    assert new["momentum"] > default["momentum"]
    assert new["mean_reversion"] < default["mean_reversion"]


def test_update_weights_step_is_bounded_and_drift_is_capped():
    default = PROFILES["neutral"].daily_weights
    one_day = dl.update_weights(default, default, {"momentum": 0.9})
    # a single day can't move a weight by more than ~LEARNING_RATE (before renormalising)
    assert one_day["momentum"] <= default["momentum"] * (1 + dl.LEARNING_RATE) * 1.05
    # repeated extreme pressure never exceeds 2x default (after renormalising it can only be smaller/similar)
    w = dict(default)
    for _ in range(60):
        w = dl.update_weights(w, default, {"momentum": 0.9, "nlp": -0.9})
    assert w["momentum"] <= default["momentum"] * dl.MAX_DRIFT[1] * 1.5
    assert w["nlp"] >= default["nlp"] * dl.MAX_DRIFT[0] * 0.5
    assert all(v > 0 for v in w.values())


def test_components_without_ic_keep_their_weight_ratio():
    default = PROFILES["bear"].daily_weights
    new = dl.update_weights(default, default, {})
    assert all(math.isclose(new[c], default[c], abs_tol=1e-3) for c in default)


_DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]


def _t(reason, pnl, held=30, pnl_pct=None, _i=[0]):
    _i[0] += 1
    return {"reason": reason, "pnl": pnl, "held": held, "day": _DAYS[_i[0] % len(_DAYS)],
            "pnl_pct": pnl_pct if pnl_pct is not None else pnl / 1000}


def test_day_params_untouched_without_enough_trades():
    p, notes = dl.tune_day_params(dict(dl.DAY_DEFAULTS), [_t("stop", -10) for _ in range(5)])
    assert p == dl.DAY_DEFAULTS
    assert "skipped" in notes[0]


def test_day_params_widen_stop_when_noise_stops_dominate():
    trades = [_t("stop", -20, held=8) for _ in range(14)] + [_t("take_profit", 40) for _ in range(4)]
    p, _ = dl.tune_day_params(dict(dl.DAY_DEFAULTS), trades)
    assert p["stop_atr"] > dl.DAY_DEFAULTS["stop_atr"]
    assert p["stop_atr"] <= dl.DAY_BOUNDS["stop_atr"][1]


def test_day_params_respect_bounds_when_losing():
    params = dict(dl.DAY_DEFAULTS)
    trades = [_t("eod", -15) for _ in range(30)]
    for _ in range(40):
        params, _ = dl.tune_day_params(params, trades)
    assert params["min_intraday_score"] <= dl.DAY_BOUNDS["min_intraday_score"][1]
    assert params["min_intraday_score"] > 0


def test_day_params_need_several_distinct_days():
    one_day = [dict(_t("eod", 5), day="2026-10-05") for _ in range(30)]
    p, notes = dl.tune_day_params(dict(dl.DAY_DEFAULTS), one_day)
    assert p == dl.DAY_DEFAULTS and "skipped" in notes[0]
