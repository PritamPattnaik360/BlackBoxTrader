import json

import pytest

from app.config import settings
from app.services import runtime_settings as rs
from app.services.adaptive import daily_learner


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp override + learned-state files, and restore every setting we touch."""
    monkeypatch.setattr(rs, "OVERRIDES_PATH", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rs, "PROFILES_PATH", tmp_path / "trading_profiles.json")
    monkeypatch.setattr(daily_learner, "STATE_PATH", tmp_path / "learned_state.json")
    daily_learner._cached["state"] = None
    for key in rs.FIELDS:
        if not key.startswith("learned.") and hasattr(settings, key):
            monkeypatch.setattr(settings, key, getattr(settings, key))
    yield
    daily_learner._cached["state"] = None


def test_coerce_validates_types_and_bounds():
    assert rs.coerce("day_trade_min_score", "0.35") == 0.35
    assert rs.coerce("max_open_positions", 7.4) == 7
    assert rs.coerce("day_trade_only", "false") is False
    assert rs.coerce("day_trade_entry_cutoff", "15:30") == "15:30"
    for key, bad in [("day_trade_min_score", 5), ("day_trade_min_score", "abc"), ("day_trade_entry_cutoff", "23:00"),
                     ("day_trade_entry_cutoff", "soon"), ("max_open_positions", 0), ("day_trade_only", "maybe"),
                     ("not_a_setting", 1), ("daily_loss_halt_pct", float("nan"))]:
        with pytest.raises(ValueError):
            rs.coerce(key, bad)


def test_update_applies_live_and_persists():
    out = rs.update({"day_trade_min_score": 0.42, "day_trade_only": False, "day_trade_entry_cutoff": "14:00"})
    assert settings.day_trade_min_score == 0.42 and settings.day_trade_only is False
    assert settings.day_trade_entry_cutoff == "14:00"
    assert out["changed"]["day_trade_min_score"]["to"] == 0.42
    saved = json.loads(rs.OVERRIDES_PATH.read_text())
    assert saved["day_trade_min_score"] == 0.42 and saved["day_trade_only"] is False


def test_invalid_batch_changes_nothing():
    before = settings.day_trade_min_score
    with pytest.raises(ValueError):
        rs.update({"day_trade_min_score": 0.5, "max_open_positions": 999})
    assert settings.day_trade_min_score == before          # all-or-nothing
    assert not rs.OVERRIDES_PATH.exists()


def test_dangerous_switch_needs_confirmation():
    with pytest.raises(ValueError):
        rs.update({"allow_short_live": True})
    assert settings.allow_short_live is False
    rs.update({"allow_short_live": True}, confirm=True)
    assert settings.allow_short_live is True
    rs.update({"allow_short_live": False})                 # turning a safety lock OFF never needs confirm
    assert settings.allow_short_live is False


def test_reapply_after_restart(monkeypatch):
    rs.update({"day_trade_min_score": 0.44, "enable_short_day_trades": False})
    monkeypatch.setattr(settings, "day_trade_min_score", 0.30)       # pretend a fresh process loaded .env
    monkeypatch.setattr(settings, "enable_short_day_trades", True)
    assert rs.apply_overrides() == 2
    assert settings.day_trade_min_score == 0.44 and settings.enable_short_day_trades is False


def test_reset_restores_baseline_and_removes_override():
    base = rs._BASELINE["day_trade_min_score"]
    rs.update({"day_trade_min_score": 0.55})
    out = rs.reset(["day_trade_min_score"])
    assert settings.day_trade_min_score == base
    assert out["restored"]["day_trade_min_score"] == base
    assert "day_trade_min_score" not in json.loads(rs.OVERRIDES_PATH.read_text())


def test_learned_day_params_are_editable_and_bounded():
    rs.update({"learned.stop_atr": 0.9, "learned.reward_risk": 1.5})
    assert daily_learner.get_day_params()["stop_atr"] == 0.9
    assert daily_learner.get_day_params()["reward_risk"] == 1.5
    with pytest.raises(ValueError):
        rs.update({"learned.stop_atr": 3.0})
    rs.reset(["learned.stop_atr"])
    assert daily_learner.get_day_params()["stop_atr"] == daily_learner.DAY_DEFAULTS["stop_atr"]


def test_snapshot_describes_every_field_with_current_and_default():
    snap = rs.snapshot()
    keys = {f["key"] for g in snap["groups"] for f in g["fields"]}
    assert keys == set(rs.FIELDS)
    f = next(f for g in snap["groups"] for f in g["fields"] if f["key"] == "day_trade_min_score")
    assert f["value"] == settings.day_trade_min_score and f["min"] == 0.10 and f["customized"] is False
    rs.update({"day_trade_min_score": 0.5})
    f = next(f for g in rs.snapshot()["groups"] for f in g["fields"] if f["key"] == "day_trade_min_score")
    assert f["customized"] is True


def test_profiles_save_load_delete_and_skip_safety_lock():
    rs.update({"day_trade_min_score": 0.45, "learned.stop_atr": 0.7, "day_trade_only": True})
    rs.save_profile("  Cautious  ")
    rs.update({"day_trade_min_score": 0.2, "learned.stop_atr": 1.0, "day_trade_only": False})
    prof = rs.list_profiles()[0]
    assert prof["name"] == "Cautious" and "allow_short_live" not in prof["values"]
    rs.apply_profile("Cautious")
    assert settings.day_trade_min_score == 0.45 and settings.day_trade_only is True
    assert daily_learner.get_day_params()["stop_atr"] == 0.7
    rs.delete_profile("Cautious")
    assert rs.list_profiles() == []
    for bad in ("", "x" * 41):
        with pytest.raises(ValueError):
            rs.save_profile(bad)
    with pytest.raises(ValueError):
        rs.apply_profile("nope")
