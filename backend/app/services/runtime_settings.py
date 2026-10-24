"""
Runtime-editable trading settings.

The Settings page edits a whitelist of trading settings live: values are validated,
applied to the running `settings` object (so the very next scan uses them), and saved to
data/runtime_settings.json so they survive restarts. Saved values take precedence over
backend/.env; "reset" removes the override and restores the .env / built-in value.

Learned day-trade parameters (stop distance, reward:risk, min intraday score) live in
the self-learning state instead (see adaptive/daily_learner.py) — they appear here as
keys prefixed "learned." — and the nightly learner keeps tuning them from the new baseline.
"""
import json
import logging
import os
from datetime import time as dtime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

OVERRIDES_PATH = Path(__file__).parents[3] / "data" / "runtime_settings.json"

# key -> spec.  type: bool | float | int | time.  `requires_confirm`: needs explicit confirmation.
FIELDS: dict[str, dict] = {
    # ── Day-trade entries ─────────────────────────────────────────────────────
    "day_trade_only": dict(group="entries", label="Day-trade-only mode", type="bool",
        help="Autopilot only opens same-day trades — no overnight/swing entries. Turn off to also allow multi-day positions."),
    "day_trade_min_score": dict(group="entries", label="Minimum composite score", type="float", min=0.10, max=0.90, step=0.01,
        help="Hard floor: a signal below this never opens a day trade (longs need ≥ this, shorts need ≤ its negative)."),
    "day_trade_min_vwap": dict(group="entries", label="Minimum VWAP score", type="float", min=0.0, max=0.90, step=0.01,
        help="How far price must be from session VWAP (above for longs, below for shorts) to confirm the move."),
    "day_trade_entry_cutoff": dict(group="entries", label="Last entry time (ET)", type="time", min="09:45", max="15:45",
        help="No new day-trade entries after this time."),
    "enable_short_day_trades": dict(group="entries", label="Short in bear markets", type="bool",
        help="When the market bias is bear, strong breakdowns are shorted (stop above, target below) and covered the same day."),
    "allow_short_live": dict(group="entries", label="Allow shorts in LIVE mode", type="bool", danger=True, requires_confirm=True,
        help="Safety lock. Shorting with real money is blocked unless this is on. A short's loss is limited only by its stop order."),
    "force_learning_trade": dict(group="entries", label="Force a small learning trade", type="bool",
        help="If a scan places nothing, place one small trade anyway to generate learning data. Not recommended."),
    # ── Exits (learned, still adjustable) ─────────────────────────────────────
    "learned.stop_atr": dict(group="exits", label="Stop distance (daily ATRs)", type="float", min=0.4, max=1.2, step=0.05,
        help="Day-trade stop-loss distance. The nightly learner keeps tuning this from the value you set."),
    "learned.reward_risk": dict(group="exits", label="Reward : risk", type="float", min=1.2, max=3.0, step=0.1,
        help="Take-profit = stop distance × this. Also tuned nightly."),
    "learned.min_intraday_score": dict(group="exits", label="Extra min intraday score", type="float", min=0.0, max=0.5, step=0.05,
        help="Extra bar on the intraday component (raised automatically if day trades lose money)."),
    # ── Risk limits ───────────────────────────────────────────────────────────
    "risk_per_trade_pct": dict(group="risk", label="Risk per trade", type="float", min=0.005, max=0.035, step=0.0025, pct=True,
        help="Share of equity risked on each trade. This is a starting value — the adaptive engine keeps adjusting it from results."),
    "max_position_pct": dict(group="risk", label="Max position size", type="float", min=0.02, max=0.25, step=0.01, pct=True,
        help="Largest single position as a share of equity."),
    "max_open_positions": dict(group="risk", label="Max open positions", type="int", min=1, max=50, step=1,
        help="Cap on simultaneous positions."),
    "daily_loss_halt_pct": dict(group="risk", label="Daily loss halt", type="float", min=0.005, max=0.20, step=0.005, pct=True,
        help="Circuit breaker: stop all new entries when the day's loss passes this."),
    "max_drawdown_halt_pct": dict(group="risk", label="Max drawdown halt", type="float", min=0.02, max=0.50, step=0.01, pct=True,
        help="Circuit breaker: halt when equity falls this far below its peak."),
    "market_crash_halt_pct": dict(group="risk", label="Market-crash halt (SPY)", type="float", min=0.01, max=0.10, step=0.005, pct=True,
        help="Circuit breaker: halt when SPY is down this much on the day."),
    "position_max_loss_pct": dict(group="risk", label="Per-position hard stop", type="float", min=0.02, max=0.50, step=0.01, pct=True,
        help="The risk guard closes any single stock position down more than this."),
    "option_max_loss_pct": dict(group="risk", label="Per-option hard stop", type="float", min=0.10, max=1.0, step=0.05, pct=True,
        help="The risk guard closes any single options position down more than this (options carry no stop order)."),
    "flatten_on_halt": dict(group="risk", label="Liquidate when the breaker trips", type="bool",
        help="On: a tripped circuit breaker closes every open position. Off: it only blocks new entries."),
    # ── Automation ────────────────────────────────────────────────────────────
    "auto_start_autonomous": dict(group="automation", label="Resume autopilot after a restart", type="bool", restart=True,
        help="If on, autopilot turns itself back on whenever the backend starts (applies from the next start)."),
    "llm_signal_enabled": dict(group="automation", label="Local LLM trading signal", type="bool",
        help="Include the local Ollama model as a signal input (market hours only). It is slow — ~15 s per ticker."),
    "learning_enabled": dict(group="automation", label="Nightly self-learning", type="bool",
        help="Each weekday at 16:30 ET the bot re-weights its algorithms and tunes day-trade parameters from results."),
}

GROUPS = [
    ("entries", "Day-trade entries"),
    ("exits", "Exits & targets"),
    ("risk", "Risk limits"),
    ("automation", "Automation"),
]

# Snapshot of the .env / built-in values, taken before any override is applied
_BASELINE: dict[str, object] = {}


def _snapshot_baseline() -> None:
    if _BASELINE:
        return
    for key in FIELDS:
        if key.startswith("learned."):
            continue
        _BASELINE[key] = getattr(settings, key, None)


_snapshot_baseline()


# ── Validation ────────────────────────────────────────────────────────────────

def _parse_time(v: str) -> dtime:
    try:
        return dtime.fromisoformat(str(v))
    except ValueError:
        raise ValueError("must be a time like 15:30")


def coerce(key: str, value):
    """Validate/convert one value. Raises ValueError with a readable message."""
    spec = FIELDS.get(key)
    if spec is None:
        raise ValueError(f"'{key}' is not an editable setting")
    t = spec["type"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError("must be true or false")
    if t in ("float", "int"):
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("must be a number")
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("must be a finite number")
        if not (spec["min"] <= v <= spec["max"]):
            raise ValueError(f"must be between {spec['min']} and {spec['max']}")
        return int(round(v)) if t == "int" else round(v, 6)
    if t == "time":
        v = _parse_time(value)
        if not (_parse_time(spec["min"]) <= v <= _parse_time(spec["max"])):
            raise ValueError(f"must be between {spec['min']} and {spec['max']}")
        return v.strftime("%H:%M")
    raise ValueError("unsupported type")


# ── Current / default values ──────────────────────────────────────────────────

def _learned_current() -> dict:
    from app.services.adaptive.daily_learner import get_day_params
    return get_day_params()


def current_value(key: str):
    if key.startswith("learned."):
        return _learned_current()[key.split(".", 1)[1]]
    if key == "risk_per_trade_pct":
        from app.services.adaptive.adaptive_engine import get_param
        return round(get_param("risk_per_trade_pct"), 6)
    return getattr(settings, key)


def default_value(key: str):
    if key.startswith("learned."):
        from app.services.adaptive.daily_learner import DAY_DEFAULTS
        return DAY_DEFAULTS[key.split(".", 1)[1]]
    return _BASELINE.get(key)


def _load_overrides() -> dict:
    try:
        if OVERRIDES_PATH.exists():
            return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not read runtime settings: {e}")
    return {}


def _save_overrides(data: dict) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OVERRIDES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, OVERRIDES_PATH)


# ── Applying ──────────────────────────────────────────────────────────────────

def _apply(key: str, value) -> None:
    if key.startswith("learned."):
        from app.services.adaptive import daily_learner
        daily_learner.set_day_param(key.split(".", 1)[1], value)
        return
    setattr(settings, key, value)
    if key == "risk_per_trade_pct":
        from app.services.adaptive import adaptive_engine
        adaptive_engine._set_params({"risk_per_trade_pct": float(value)})


def apply_overrides() -> int:
    """Called once at startup: re-apply every saved override. Returns how many were applied."""
    n = 0
    for key, raw in _load_overrides().items():
        if key.startswith("learned."):
            continue                      # learned params persist in learned_state.json
        try:
            _apply(key, coerce(key, raw))
            n += 1
        except Exception as e:
            logger.warning(f"Ignoring saved setting {key}={raw!r}: {e}")
    if n:
        logger.info(f"Applied {n} saved trading setting override(s)")
    return n


def update(values: dict, confirm: bool = False) -> dict:
    """Validate everything first, then apply and persist. Returns {'changed': {...}}. Raises ValueError."""
    clean, errors = {}, {}
    for key, raw in values.items():
        try:
            clean[key] = coerce(key, raw)
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise ValueError(json.dumps(errors))

    # Dangerous switches need an explicit confirmation
    for key, v in clean.items():
        if FIELDS[key].get("requires_confirm") and v is True and not confirm:
            raise ValueError(json.dumps({key: "needs explicit confirmation"}))

    overrides = _load_overrides()
    changed = {}
    for key, v in clean.items():
        before = current_value(key)
        _apply(key, v)
        if not key.startswith("learned."):
            overrides[key] = v
        changed[key] = {"from": before, "to": v}
        logger.info(f"[CONFIG] {key}: {before!r} -> {v!r}")
    _save_overrides(overrides)
    return {"changed": changed}


def reset(keys: list[str] | None = None) -> dict:
    overrides = _load_overrides()
    targets = keys or list(FIELDS)
    restored = {}
    for key in targets:
        if key not in FIELDS:
            continue
        base = default_value(key)
        if base is None:
            continue
        _apply(key, base)
        overrides.pop(key, None)
        restored[key] = base
    _save_overrides(overrides)
    return {"restored": restored}


# ── Saved profiles ────────────────────────────────────────────────────────────
# A profile is a named copy of the editable settings. Safety locks that need explicit
# confirmation (e.g. shorting in live mode) are never stored or applied by a profile.

PROFILES_PATH = Path(__file__).parents[3] / "data" / "trading_profiles.json"
MAX_PROFILES = 30


def _profile_keys() -> list[str]:
    return [k for k, spec in FIELDS.items() if not spec.get("requires_confirm")]


def _load_profiles() -> dict:
    try:
        if PROFILES_PATH.exists():
            return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not read trading profiles: {e}")
    return {}


def _save_profiles(data: dict) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, PROFILES_PATH)


def _clean_name(name: str) -> str:
    name = " ".join(str(name).split())
    if not name or len(name) > 40:
        raise ValueError("name must be 1-40 characters")
    if any(c in name for c in "/?#%") or "\\" in name:
        raise ValueError("name can't contain / ? # % or a backslash")
    return name


def list_profiles() -> list[dict]:
    profiles = _load_profiles()
    return [{"name": n, "saved_at": p.get("saved_at"), "values": p.get("values", {})}
            for n, p in sorted(profiles.items(), key=lambda kv: kv[0].lower())]


def save_profile(name: str) -> dict:
    """Store the current values of every editable setting under `name` (overwrites)."""
    from datetime import datetime, timezone
    name = _clean_name(name)
    profiles = _load_profiles()
    if name not in profiles and len(profiles) >= MAX_PROFILES:
        raise ValueError(f"at most {MAX_PROFILES} profiles")
    profiles[name] = {"saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "values": {k: current_value(k) for k in _profile_keys()}}
    _save_profiles(profiles)
    return {"name": name}


def apply_profile(name: str) -> dict:
    profiles = _load_profiles()
    if name not in profiles:
        raise ValueError(f"no profile named '{name}'")
    keys = set(_profile_keys())
    values = {k: v for k, v in profiles[name]["values"].items() if k in keys}
    return update(values)


def delete_profile(name: str) -> None:
    profiles = _load_profiles()
    if profiles.pop(name, None) is None:
        raise ValueError(f"no profile named '{name}'")
    _save_profiles(profiles)


def snapshot() -> dict:
    """Everything the UI needs to render the editor."""
    saved = _load_overrides()
    groups = []
    for gid, label in GROUPS:
        fields = []
        for key, spec in FIELDS.items():
            if spec["group"] != gid:
                continue
            value, default = current_value(key), default_value(key)
            fields.append({
                "key": key, "label": spec["label"], "type": spec["type"], "help": spec["help"],
                "value": value, "default": default,
                "customized": (key in saved) or (default is not None and value != default),
                "min": spec.get("min"), "max": spec.get("max"), "step": spec.get("step"),
                "pct": spec.get("pct", False), "danger": spec.get("danger", False),
                "requires_confirm": spec.get("requires_confirm", False), "restart": spec.get("restart", False),
            })
        groups.append({"id": gid, "label": label, "fields": fields})
    return {"groups": groups, "trading_mode": settings.trading_mode}
