from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.adaptive import daily_learner, patterns
from app.services.trading_engine import executor

ET = ZoneInfo("America/New_York")


def _trade(i, hour, pnl, score=0.4, bias="bull", side="long", ticker="AAA", features=None):
    when = datetime(2026, 9, 1, hour, 0, tzinfo=ET) + timedelta(days=i)
    return {"entry_time": when.astimezone(timezone.utc), "pnl": pnl, "score": score, "bias": bias,
            "side": side, "ticker": ticker, "features": features}


def test_hour_that_loses_in_train_and_test_is_flagged():
    trades = [_trade(i, 14, -10) for i in range(25)] + [_trade(i, 10, 10) for i in range(25)]
    rep = patterns.analyze(trades)
    assert [b["bucket"] for b in rep["avoid"] if b["dim"] == "hour"] == ["14:00"]
    assert patterns.avoid_hours(rep) == [14]


def test_recent_recovery_is_not_flagged():
    # lost early, but the held-out (latest) trades in that hour are winners
    trades = [_trade(i, 14, -10) for i in range(20)] + [_trade(i + 20, 14, 15) for i in range(10)]
    rep = patterns.analyze(trades)
    assert not [b for b in rep["avoid"] if b["dim"] == "hour"]


def test_small_buckets_are_ignored():
    rep = patterns.analyze([_trade(i, 14, -10) for i in range(10)])
    assert rep["buckets"] == [] and patterns.avoid_hours(rep) == []


def test_feature_bands_and_missing_features():
    keys = patterns.trade_keys(_trade(0, 11, 1, score=-0.62, features={"rvol": 1.8, "vix": 27}))
    assert keys["score"] == "0.50-0.70" and keys["rvol"] == "1.5-2.5x" and keys["vix"] == "22-30"
    assert patterns.trade_keys(_trade(0, 11, 1))["rvol"] is None


def test_avoid_hours_capped():
    trades = []
    for h in (10, 11, 12):
        trades += [_trade(i, h, -5 * (h - 9)) for i in range(25)]
    assert len(patterns.avoid_hours(patterns.analyze(trades))) == patterns.MAX_AVOID_HOURS


def test_executor_blocks_learned_hour(monkeypatch):
    monkeypatch.setattr(daily_learner, "get_avoid_hours", lambda: [14])
    assert "14:00" in executor._pattern_block_reason(datetime(2026, 10, 21, 14, 5, tzinfo=ET))
    assert executor._pattern_block_reason(datetime(2026, 10, 21, 10, 5, tzinfo=ET)) is None


def test_entry_features_keeps_signal_state():
    f = executor._entry_features({"rvol": 2.1, "intraday_vwap": 0.5, "weights": {"x": 1}}, 0.5, 1.0, "day")
    assert f["rvol"] == 2.1 and f["style"] == "day" and "weights" not in f
