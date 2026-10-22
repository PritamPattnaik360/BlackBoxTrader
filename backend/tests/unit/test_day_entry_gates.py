from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.services.trading_engine.executor import _day_entry_block_reason

ET = ZoneInfo("America/New_York")
MORNING = datetime(2026, 10, 21, 10, 15, tzinfo=ET)


@pytest.fixture(autouse=True)
def gate_settings(monkeypatch):
    monkeypatch.setattr(settings, "day_trade_min_score", 0.30)
    monkeypatch.setattr(settings, "day_trade_entry_cutoff", "12:00")


def test_strong_morning_entry_allowed():
    assert _day_entry_block_reason(0.45, MORNING) is None


def test_floor_is_inclusive():
    assert _day_entry_block_reason(0.30, MORNING) is None


def test_sub_floor_score_blocked():
    assert "floor" in _day_entry_block_reason(0.18, MORNING)


def test_missing_score_blocked():
    assert _day_entry_block_reason(None, MORNING) is not None


def test_entry_after_cutoff_blocked():
    late = datetime(2026, 10, 21, 13, 5, tzinfo=ET)
    assert "cutoff" in _day_entry_block_reason(0.6, late)


def test_entry_at_cutoff_allowed():
    assert _day_entry_block_reason(0.6, datetime(2026, 10, 21, 12, 0, tzinfo=ET)) is None
