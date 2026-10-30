from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.adaptive import patterns
from app.services.trading_engine import loss_guard

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 30, 14, 0, tzinfo=ET)


def _stop(ticker, minutes_ago=0, days_ago=0):
    return {"ticker": ticker, "exit_time": (NOW - timedelta(minutes=minutes_ago, days=days_ago)).astimezone(timezone.utc)}


def test_no_stops_allows_entry():
    assert loss_guard.block_reason("GPN", [], NOW) is None


def test_ticker_stopped_today_is_not_reentered():
    assert "earlier today" in loss_guard.block_reason("GPN", [_stop("GPN", 30)], NOW)
    assert loss_guard.block_reason("AAPL", [_stop("GPN", 30)], NOW) is None


def test_daily_stop_limit_blocks_everything():
    stops = [_stop("A", 10), _stop("B", 20), _stop("C", 30)]
    assert "no more day trades" in loss_guard.block_reason("Z", stops, NOW)
    assert loss_guard.block_reason("Z", stops[:2], NOW) is None


def test_repeat_offender_paused_for_window_then_released():
    stops = [_stop("FIX", days_ago=1), _stop("FIX", days_ago=3)]
    assert "paused" in loss_guard.block_reason("FIX", stops, NOW)
    old = [_stop("FIX", days_ago=1), _stop("FIX", days_ago=6)]
    assert loss_guard.block_reason("FIX", old, NOW) is None


def test_post_mortem_describes_losses():
    losses = [dict(ticker="GPN", pnl=-227, entry_price=96.27, stop_price=94.02, held=3, score=0.55),
              dict(ticker="GPN", pnl=-224, entry_price=95.64, stop_price=93.4, held=1, score=0.45)]
    text = "\n".join(patterns.post_mortem(losses))
    assert "2 stop-out" in text and "re-entered" in text and "within 5 minutes" in text
    assert patterns.post_mortem([]) == []
