import math

import pandas as pd

from app.services.strategy import market_bias
from app.services.quant_engine import intraday
from app.services.trading_engine import day_journal
from app.models.day_trade import DayTrade
from datetime import datetime, timezone, timedelta


def test_profile_weights_sum_to_one():
    for p in market_bias.PROFILES.values():
        assert math.isclose(sum(p.daily_weights.values()), 1.0, abs_tol=1e-9), p.name
        assert math.isclose(sum(p.intraday_weights.values()), 1.0, abs_tol=1e-9), p.name


def test_with_llm_keeps_total_at_one():
    for p in market_bias.PROFILES.values():
        w = market_bias.with_llm(p.daily_weights)
        assert math.isclose(sum(w.values()), 1.0, abs_tol=1e-9)
        assert math.isclose(w["llm"], 0.20)


def test_bear_is_harder_to_buy_and_easier_to_exit():
    bull, bear = market_bias.PROFILES["bull"], market_bias.PROFILES["bear"]
    assert bear.buy_thr_adj > bull.buy_thr_adj
    assert bear.sell_thr_adj > bull.sell_thr_adj      # less negative → exits trigger sooner
    assert bear.size_mult < bull.size_mult


def _bars(closes, vol=1000):
    return pd.DataFrame({"open": closes, "high": [c * 1.001 for c in closes],
                         "low": [c * 0.999 for c in closes], "close": closes,
                         "volume": [vol] * len(closes)})


def test_intraday_fade_buys_washed_out_dip_and_ignores_flat_tape():
    flat = _bars([100.0] * 30)
    dip = _bars([100.0] * 15 + [100 - i * 0.35 for i in range(1, 16)])
    assert intraday._fade_signal(flat) == 0.0
    assert intraday._fade_signal(dip) > 0.0


def test_close_computes_pnl_and_hold_time():
    entry = datetime.now(timezone.utc)
    row = DayTrade(ticker="X", qty=10, entry_price=50.0, entry_time=entry)
    day_journal._close(row, 52.0, "take_profit", entry + timedelta(minutes=30))
    assert row.status == "closed"
    assert row.pnl == 20.0
    assert row.held_minutes == 30
    assert row.exit_reason == "take_profit"
