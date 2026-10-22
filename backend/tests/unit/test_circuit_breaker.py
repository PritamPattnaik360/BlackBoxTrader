import pytest

from app.config import settings
from app.services.risk_manager import portfolio_limits as pl
from app.services.trading_engine.executor import _closes_position


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "STATE_PATH", tmp_path / "risk_state.json")
    monkeypatch.setattr(pl, "_state", {
        "peak_equity": 0.0, "day_start_equity": 0.0, "halted": False,
        "reason": None, "detail": None, "tripped_at": None, "trip_date": None,
    })
    monkeypatch.setattr(settings, "daily_loss_halt_pct", 0.05)
    monkeypatch.setattr(settings, "max_drawdown_halt_pct", 0.15)
    monkeypatch.setattr(settings, "market_crash_halt_pct", 0.03)


def test_small_loss_does_not_trip():
    pl.update_equity(100_000, day_start_equity=100_000)
    assert not pl.evaluate(97_000, spy_change_pct=-0.01)


def test_daily_loss_trips_against_prior_close():
    pl.update_equity(100_000, day_start_equity=100_000)
    assert pl.evaluate(94_900)
    assert pl.status()["reason"] == "daily_loss"


def test_drawdown_from_peak_trips():
    pl.update_equity(120_000)
    pl.update_equity(103_000, day_start_equity=103_000)   # flat today, but 14% off peak
    assert not pl.evaluate(103_000)
    assert pl.evaluate(101_000)
    assert pl.status()["reason"] == "drawdown"


def test_market_crash_trips():
    pl.update_equity(100_000, day_start_equity=100_000)
    assert pl.evaluate(100_000, spy_change_pct=-0.035)
    assert pl.status()["reason"] == "market_crash"


def test_daily_halt_clears_next_session_but_drawdown_is_sticky(monkeypatch):
    pl.update_equity(100_000, day_start_equity=100_000)
    pl.evaluate(94_000)
    monkeypatch.setattr(pl, "_today", lambda: "2099-01-02")
    pl.update_equity(94_000, day_start_equity=94_000)
    assert not pl.evaluate(94_000)

    pl.kill()
    assert pl.evaluate(94_000)   # manual halt survives a new day
    monkeypatch.setattr(pl, "_today", lambda: "2099-01-03")
    assert pl.evaluate(94_000)


def test_resume_rebases_peak_so_drawdown_does_not_retrip():
    pl.update_equity(120_000)
    pl.update_equity(100_000, day_start_equity=100_000)
    assert pl.evaluate(100_000)
    pl.resume(current_equity=100_000)
    assert not pl.evaluate(100_000)


def test_halt_persists_to_disk(tmp_path):
    pl.kill()
    saved = (tmp_path / "risk_state.json").read_text()
    assert '"halted": true' in saved and '"manual"' in saved


def test_exits_are_allowed_while_halted():
    stock = {"ticker": "AAPL", "option_type": None}
    call = {"ticker": "AAPL", "option_type": "call"}
    assert _closes_position("SELL", stock)
    assert not _closes_position("BUY", stock)
    assert not _closes_position("BUY", None)
    assert not _closes_position("SELL", None)      # would open a put
    assert _closes_position("SELL", call)          # closes the call
    assert not _closes_position("BUY", call)
