"""Regression tests: exits close the whole position, no stray stop on exits, short day trades,
and the single-flight scan lock."""
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.models.day_trade import DayTrade
from app.services.nlp_engine.aggregator import CompositeSignal
from app.services.trading_engine import broker, day_journal, executor

ET = ZoneInfo("America/New_York")
MORNING = datetime(2026, 10, 21, 10, 15, tzinfo=ET)


def _signal(direction: str, ticker: str = "TSLA") -> CompositeSignal:
    return CompositeSignal(ticker, -0.5 if direction == "SELL" else 0.5, 0.8, direction, 0, None, None, [],
                           datetime.now(timezone.utc))


@pytest.fixture
def fake_broker(monkeypatch):
    """Executor wired to an in-memory broker; records every call."""
    calls = {"flatten": [], "market": [], "stop": [], "bracket": [], "journal": [], "saved": []}
    state = {"positions": []}

    monkeypatch.setattr(executor, "_dry_run", False)
    monkeypatch.setattr(executor, "get_snapshot", lambda t: {"price": 100.0})
    monkeypatch.setattr(broker, "get_positions", lambda: state["positions"])
    monkeypatch.setattr(broker, "flatten_symbol", lambda s: calls["flatten"].append(s))
    monkeypatch.setattr(broker, "submit_market_order", lambda *a, **k: calls["market"].append(a) or {})
    monkeypatch.setattr(broker, "submit_stop_order", lambda *a, **k: calls["stop"].append(a) or {})
    monkeypatch.setattr(broker, "submit_bracket_order", lambda *a, **k: calls["bracket"].append((a, k)) or {})
    monkeypatch.setattr(executor.portfolio_limits, "is_halted", lambda eq: False)
    monkeypatch.setattr(executor.portfolio_limits, "check_position_count", lambda n: True)
    monkeypatch.setattr(executor.stop_loss, "calculate_atr", lambda t: 2.0)
    monkeypatch.setattr(executor, "_pdt_allows_day_trade", lambda eq: True)
    monkeypatch.setattr(settings, "enable_options_trading", False)

    async def fake_save(**kw):
        calls["saved"].append(kw)

    async def fake_open(*a, **k):
        calls["journal"].append((a, k))

    monkeypatch.setattr(executor, "_save_order", fake_save)
    monkeypatch.setattr(day_journal, "open_trade", fake_open)
    return calls, state


def _long(ticker="TSLA", qty=4.0):
    return {"ticker": ticker, "contract_symbol": None, "option_type": None, "qty": qty,
            "avg_entry_price": 90.0, "current_price": 100.0}


# ── Bug 1 + 2: exits ──────────────────────────────────────────────────────────

def test_sell_closes_whole_held_quantity_without_sizing_or_stray_stop(fake_broker, monkeypatch):
    calls, state = fake_broker
    state["positions"] = [_long("TSLA", 4.0)]
    # Equity big enough that the risk sizer would have asked for far more than 4 shares
    res = asyncio.run(executor.execute_signal(_signal("SELL"), 0, 1_000_000, style="swing"))
    assert res["action"] == "submitted"
    assert calls["flatten"] == ["TSLA"]            # cancels stop/bracket legs, then liquidates all of it
    assert calls["market"] == []                   # no hand-sized market order (this is what failed before)
    assert calls["stop"] == []                     # and no opposite-side (buy) stop
    assert calls["saved"][0]["side"] == "sell" and calls["saved"][0]["qty"] == 4.0


def test_sell_without_position_is_skipped(fake_broker):
    calls, _ = fake_broker
    res = asyncio.run(executor.execute_signal(_signal("SELL"), 0, 100_000, style="swing"))
    assert res["action"] == "skip"
    assert calls["flatten"] == [] and calls["bracket"] == [] and calls["market"] == []


def test_exit_allowed_even_in_day_trade_only_mode(fake_broker, monkeypatch):
    calls, state = fake_broker
    monkeypatch.setattr(settings, "day_trade_only", True)
    state["positions"] = [_long("WDC", 7.0)]
    res = asyncio.run(executor.execute_signal(_signal("SELL", "WDC"), 0, 100_000))
    assert res["action"] == "submitted" and calls["flatten"] == ["WDC"]


# ── Short day trades ──────────────────────────────────────────────────────────

@pytest.fixture
def short_ready(monkeypatch):
    monkeypatch.setattr(settings, "enable_short_day_trades", True)
    monkeypatch.setattr(settings, "allow_short_live", False)
    monkeypatch.setattr(settings, "trading_mode", "paper")
    monkeypatch.setattr(settings, "day_trade_min_score", 0.30)
    monkeypatch.setattr(settings, "day_trade_min_vwap", 0.35)
    monkeypatch.setattr(settings, "day_trade_entry_cutoff", "23:59")
    monkeypatch.setattr(executor, "_shortable_block_reason", lambda t: None)


def test_short_gate_requires_strong_negative_score_and_vwap(short_ready):
    assert executor._short_entry_block_reason(-0.45, MORNING, -0.5) is None
    assert "not below" in executor._short_entry_block_reason(-0.10, MORNING, -0.5)
    assert "VWAP" in executor._short_entry_block_reason(-0.45, MORNING, -0.1)
    assert executor._short_entry_block_reason(0.45, MORNING, 0.5) is not None
    assert executor._short_entry_block_reason(None, MORNING, None) is not None


def test_short_gate_respects_flags_and_live_lock(short_ready, monkeypatch):
    monkeypatch.setattr(settings, "enable_short_day_trades", False)
    assert "disabled" in executor._short_entry_block_reason(-0.5, MORNING, -0.5)
    monkeypatch.setattr(settings, "enable_short_day_trades", True)
    monkeypatch.setattr(settings, "trading_mode", "live")
    assert "ALLOW_SHORT_LIVE" in executor._short_entry_block_reason(-0.5, MORNING, -0.5)
    monkeypatch.setattr(settings, "allow_short_live", True)
    assert executor._short_entry_block_reason(-0.5, MORNING, -0.5) is None


def test_short_entry_submits_sell_bracket_with_stop_above_and_target_below(fake_broker, short_ready):
    calls, _ = fake_broker
    res = asyncio.run(executor.execute_signal(
        _signal("SELL", "SPY"), 0, 100_000, style="short", quant_score=-0.5, vwap_score=-0.6, bias="bear"))
    assert res["action"] == "submitted"
    (args, kwargs) = calls["bracket"][0]
    ticker, qty, stop, target = args[:4]
    assert kwargs.get("side") == "sell"
    assert stop > 100.0 > target                    # short: stop above entry, take-profit below
    assert calls["market"] == []                    # the bracket was accepted, no fallback
    assert calls["journal"][0][1]["side"] == "short"


def test_short_blocked_when_not_a_short_setup_or_not_shortable(fake_broker, short_ready, monkeypatch):
    calls, _ = fake_broker
    weak = asyncio.run(executor.execute_signal(
        _signal("SELL", "SPY"), 0, 100_000, style="short", quant_score=-0.1, vwap_score=-0.6, bias="bear"))
    assert weak["action"] == "skip" and calls["bracket"] == []
    monkeypatch.setattr(executor, "_shortable_block_reason", lambda t: "SPY is hard to borrow")
    hard = asyncio.run(executor.execute_signal(
        _signal("SELL", "SPY"), 0, 100_000, style="short", quant_score=-0.5, vwap_score=-0.6, bias="bear"))
    assert hard["action"] == "skip" and "borrow" in hard["reason"] and calls["bracket"] == []


def test_buy_signal_covers_an_open_short_even_in_day_only_mode(fake_broker, monkeypatch):
    calls, state = fake_broker
    monkeypatch.setattr(settings, "day_trade_only", True)
    state["positions"] = [_long("SPY", -10.0)]
    res = asyncio.run(executor.execute_signal(_signal("BUY", "SPY"), 0, 100_000))
    assert res["action"] == "submitted" and calls["flatten"] == ["SPY"]
    assert calls["saved"][0]["side"] == "buy"


def test_short_not_opened_when_already_short(fake_broker, short_ready):
    calls, state = fake_broker
    state["positions"] = [_long("SPY", -10.0)]
    res = asyncio.run(executor.execute_signal(
        _signal("SELL", "SPY"), 0, 100_000, style="short", quant_score=-0.5, vwap_score=-0.6, bias="bear"))
    assert res["action"] == "skip" and calls["bracket"] == []


# ── Journal maths for shorts ──────────────────────────────────────────────────

def test_short_pnl_is_positive_when_price_falls():
    entry = datetime.now(timezone.utc)
    row = DayTrade(ticker="SPY", qty=10, entry_price=100.0, entry_time=entry, side="short")
    day_journal._close(row, 98.0, "take_profit", entry + timedelta(minutes=20))
    assert row.pnl == 20.0 and row.pnl_pct == 0.02

    loser = DayTrade(ticker="SPY", qty=10, entry_price=100.0, entry_time=entry, side="short")
    day_journal._close(loser, 103.0, "stop", entry + timedelta(minutes=5))
    assert loser.pnl == -30.0 and loser.pnl < 0


def test_long_pnl_unchanged():
    entry = datetime.now(timezone.utc)
    row = DayTrade(ticker="X", qty=10, entry_price=50.0, entry_time=entry, side="long")
    day_journal._close(row, 52.0, "take_profit", entry + timedelta(minutes=30))
    assert row.pnl == 20.0


# ── Bug 3: single-flight scan lock ───────────────────────────────────────────

def test_overlapping_scans_run_once(monkeypatch):
    from app.tasks import signal_scan
    runs = []

    async def slow_scan():
        runs.append(1)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(signal_scan, "_run_signal_scan", slow_scan)

    async def burst():
        await asyncio.gather(signal_scan.run_signal_scan(), signal_scan.run_signal_scan(),
                             signal_scan.run_signal_scan())
        await signal_scan.run_signal_scan()          # after the burst finished, a new scan is allowed

    asyncio.run(burst())
    assert len(runs) == 2
