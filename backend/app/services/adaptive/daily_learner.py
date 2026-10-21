"""
Daily self-improvement job.

Runs after the close each trading day and learns from what actually happened:

1. Component weights  — every stored signal carries the score of each algorithm
   (intraday, momentum, mean-reversion, technical, trend lines, news). For each
   (market bias, daily|intraday) group we measure how well each score ranked the
   forward return (Spearman rank-IC) and shift weight toward the algorithms that
   predicted well and away from those that didn't.
       daily-mode signals    → return from the last close to the next trading day's close
       intraday-mode signals → return from the signal's 5-min bar to that day's close
2. Day-trade parameters — stop distance, reward:risk and minimum intraday score,
   tuned from the day-trade journal (how trades exited, hold times, expectancy).

Guard-rails (it must not be able to wreck itself):
  * needs enough samples across >= MIN_DAYS distinct trading days
  * max ±MAX_STEP relative change per component per day
  * every weight stays within [0.5x, 2x] of its hand-set default, then renormalises
  * day-trade params move one 10% step per day inside hard bounds
  * everything is written to data/training/learned_state.json (versioned in git,
    with a history log) and to the adaptive events feed; reset() restores defaults
  * LEARNING_ENABLED=false turns the whole thing off
"""
import asyncio
import json
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
MARKET_CLOSE = dtime(16, 0)
SETTLED = dtime(16, 5)      # after this, today's daily bar is final
STATE_PATH = Path(__file__).parents[4] / "data" / "training" / "learned_state.json"

LOOKBACK_DAYS = 30
MIN_SAMPLES   = 60      # per (bias, mode) group, after de-duplication
MIN_DAYS      = 3       # distinct trading days in the sample
MIN_NONZERO   = 0.30    # a component must be non-zero this often to be judged
LEARNING_RATE = 0.15    # max relative change per day = LR (when |IC| >= IC_FULL)
IC_FULL       = 0.15    # |IC| at which the full step is taken
MAX_DRIFT     = (0.5, 2.0)   # bounds relative to the default weight

MIN_DAY_TRADES = 15
DAY_BOUNDS = {"stop_atr": (0.4, 1.2), "reward_risk": (1.2, 3.0), "min_intraday_score": (0.0, 0.5)}
DAY_DEFAULTS = {"stop_atr": 0.6, "reward_risk": 2.0, "min_intraday_score": 0.0}

COMPONENTS = ("intraday", "nlp", "momentum", "mean_reversion", "technical", "trendlines")


# ── State ─────────────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {"version": 1, "updated": None, "weights": {}, "day": dict(DAY_DEFAULTS), "history": []}


def load_state() -> dict:
    try:
        if STATE_PATH.exists():
            s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            s.setdefault("weights", {})
            s.setdefault("history", [])
            s["day"] = {**DAY_DEFAULTS, **s.get("day", {})}
            return s
    except Exception as e:
        logger.warning(f"Could not read learned state: {e}")
    return _empty_state()


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = datetime.now(timezone.utc).isoformat()
    state["history"] = state["history"][-60:]
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8", newline="\n")


_cached: dict = {"mtime": None, "state": None}


def _state_cached() -> dict:
    """Cheap read used on the hot path; reloads only when the file changes."""
    try:
        m = STATE_PATH.stat().st_mtime if STATE_PATH.exists() else None
    except OSError:
        m = None
    if _cached["state"] is None or _cached["mtime"] != m:
        _cached.update(mtime=m, state=load_state())
    return _cached["state"]


def get_learned_weights(bias: str, mode: str) -> dict | None:
    """Learned weights for (bias, 'daily'|'intraday'), or None to use the defaults."""
    return _state_cached().get("weights", {}).get(bias, {}).get(mode)


def get_day_params() -> dict:
    return _state_cached()["day"]


def reset() -> None:
    save_state(_empty_state())
    _cached["state"] = None


# ── Pure learning maths (unit-tested) ─────────────────────────────────────────

def rank_ic(x: pd.Series, y: pd.Series) -> float | None:
    """Spearman rank correlation; None if undefined (constant series, too few points)."""
    df = pd.concat([x, y], axis=1).dropna()
    if len(df) < 20 or df.iloc[:, 0].nunique() < 3 or df.iloc[:, 1].nunique() < 3:
        return None
    ic = df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank())
    return None if pd.isna(ic) else float(ic)


def update_weights(current: dict, default: dict, ics: dict) -> dict:
    """
    Move `current` weights one bounded step toward the components with positive IC.
    Components with no usable IC keep their weight. Result is bounded relative to
    `default` and renormalised to sum to 1.
    """
    new = {}
    for c, w in current.items():
        ic = ics.get(c)
        if ic is not None:
            step = LEARNING_RATE * float(np.clip(ic / IC_FULL, -1.0, 1.0))
            w = w * (1.0 + step)
        lo, hi = default[c] * MAX_DRIFT[0], default[c] * MAX_DRIFT[1]
        new[c] = float(np.clip(w, lo, hi))
    total = sum(new.values())
    return {c: round(v / total, 4) for c, v in new.items()}


def tune_day_params(params: dict, trades: list[dict]) -> tuple[dict, list[str]]:
    """One bounded step on the day-trade parameters from closed journal trades."""
    notes: list[str] = []
    p = dict(params)
    n = len(trades)
    days = len({t["day"] for t in trades if t.get("day")})
    if n < MIN_DAY_TRADES or days < MIN_DAYS:
        return p, [f"day-trade tuning skipped: {n}/{MIN_DAY_TRADES} closed trades over {days}/{MIN_DAYS} days"]

    def rate(reason):  return sum(1 for t in trades if t["reason"] == reason) / n
    stops = [t for t in trades if t["reason"] == "stop"]
    eods  = [t for t in trades if t["reason"] == "eod"]
    total_pnl = sum(t["pnl"] for t in trades)

    def clip(k, v): return round(float(np.clip(v, *DAY_BOUNDS[k])), 3)

    if rate("stop") > 0.55 and stops and np.mean([t["held"] for t in stops]) < 20:
        p["stop_atr"] = clip("stop_atr", p["stop_atr"] * 1.10)
        notes.append(f"stops {rate('stop'):.0%} of exits and hit within ~{np.mean([t['held'] for t in stops]):.0f}m "
                     f"-> widen stop to {p['stop_atr']} ATR")
    if rate("take_profit") < 0.15 and eods and np.mean([t["pnl_pct"] for t in eods]) > 0:
        p["reward_risk"] = clip("reward_risk", p["reward_risk"] * 0.90)
        notes.append(f"targets hit only {rate('take_profit'):.0%} while EOD exits are profitable "
                     f"-> reward:risk {p['reward_risk']}")
    elif rate("take_profit") > 0.50:
        p["reward_risk"] = clip("reward_risk", p["reward_risk"] * 1.10)
        notes.append(f"targets hit {rate('take_profit'):.0%} -> stretch reward:risk to {p['reward_risk']}")
    if n >= 25 and total_pnl < 0:
        p["min_intraday_score"] = clip("min_intraday_score", p["min_intraday_score"] + 0.05)
        notes.append(f"net P&L ${total_pnl:,.0f} over {n} trades -> require intraday score "
                     f">= {p['min_intraday_score']}")
    return p, notes or ["day-trade parameters unchanged"]


# ── Data: forward returns for stored signals ──────────────────────────────────

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    return df


def _forward_returns(rows: list[dict]) -> pd.DataFrame:
    """Blocking. Adds a 'fwd' column (forward return) to each signal row; drops those without."""
    import yfinance as yf

    out = []
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    now_et = datetime.now(ET)

    for ticker, sigs in by_ticker.items():
        try:
            daily = _flatten(yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True))
            intra = None
            if any(s["mode"] == "intraday" for s in sigs):
                intra = _flatten(yf.download(ticker, period="1mo", interval="5m", progress=False, auto_adjust=True))
                if not intra.empty:
                    intra.index = (intra.index.tz_localize("UTC") if intra.index.tz is None else intra.index).tz_convert(ET)
            if daily.empty:
                continue
            daily.index = pd.to_datetime(daily.index).tz_localize(None)
            closes = daily["close"]
        except Exception as e:
            logger.debug(f"forward-return fetch failed for {ticker}: {e}")
            continue

        for s in sigs:
            t = s["time"].astimezone(ET)
            fwd = None
            if s["mode"] == "intraday" and intra is not None and not intra.empty:
                day = intra[intra.index.date == t.date()]
                complete = t.date() < now_et.date() or now_et.time() > SETTLED
                before = day[day.index <= t]
                if complete and len(before) and len(day):
                    entry, exit_ = float(before["close"].iloc[-1]), float(day["close"].iloc[-1])
                    fwd = exit_ / entry - 1 if entry > 0 else None
            else:
                # Entry = last close before the signal; exit = the next trading day's close
                after_close = t.time() >= MARKET_CLOSE
                entry_date = pd.Timestamp(t.date()) if after_close else pd.Timestamp(t.date()) - pd.Timedelta(days=1)
                prior = closes[closes.index <= entry_date]
                nxt = closes[closes.index > entry_date]
                if (len(prior) and len(nxt)
                        and (nxt.index[0].date() < now_et.date() or now_et.time() > SETTLED)):
                    entry, exit_ = float(prior.iloc[-1]), float(nxt.iloc[0])
                    fwd = exit_ / entry - 1 if entry > 0 else None
            if fwd is not None:
                out.append({**s, "fwd": fwd})
    return pd.DataFrame(out)


async def _load_signals() -> list[dict]:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.signal import Signal

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    async with AsyncSessionLocal() as db:
        sigs = (await db.execute(select(Signal).where(Signal.created_at >= cutoff))).scalars().all()

    rows = []
    for s in sigs:
        q = (s.raw_headlines or {}).get("_quant") if isinstance(s.raw_headlines, dict) else None
        if not q or "bias" not in q or "mode" not in q:
            continue                       # signals from before bias tracking carry no usable label
        t = s.created_at if s.created_at.tzinfo else s.created_at.replace(tzinfo=timezone.utc)
        rows.append({
            "ticker": s.ticker, "time": t, "bias": q["bias"], "mode": q["mode"],
            **{c: float(q.get(c, 0.0) or 0.0) for c in COMPONENTS},
        })
    return rows


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Signals every 5 minutes are near-duplicates; keep the last per ticker per hour."""
    df = df.copy()
    df["bucket"] = df["time"].apply(lambda t: t.astimezone(ET).strftime("%Y-%m-%d %H"))
    return df.sort_values("time").groupby(["ticker", "bucket", "mode"], as_index=False).last()


# ── Orchestration ─────────────────────────────────────────────────────────────

async def _learn_weights(state: dict, report: list[str]) -> None:
    from app.services.strategy.market_bias import PROFILES

    rows = await _load_signals()
    if not rows:
        report.append("weights: no labelled signals yet (signals since bias tracking began are needed)")
        return
    df = await asyncio.to_thread(_forward_returns, rows)
    if df.empty:
        report.append("weights: no signals old enough to have a forward return yet")
        return
    df = _dedupe(df)

    for bias in ("bull", "neutral", "bear"):
        for mode in ("daily", "intraday"):
            g = df[(df["bias"] == bias) & (df["mode"] == mode)]
            tag = f"{bias}/{mode}"
            days = g["time"].apply(lambda t: t.astimezone(ET).date()).nunique() if len(g) else 0
            if len(g) < MIN_SAMPLES or days < MIN_DAYS:
                report.append(f"weights {tag}: {len(g)} samples over {days}d (need {MIN_SAMPLES} over {MIN_DAYS}d) - unchanged")
                continue
            profile = PROFILES[bias]
            default = profile.intraday_weights if mode == "intraday" else profile.daily_weights
            current = state["weights"].get(bias, {}).get(mode, default)
            ics = {}
            for c in default:
                if c == "llm" or c not in g:
                    continue
                if (g[c] != 0).mean() < MIN_NONZERO:
                    continue
                ics[c] = rank_ic(g[c], g["fwd"])
            ics = {c: v for c, v in ics.items() if v is not None}
            new = update_weights(current, default, ics)
            state["weights"].setdefault(bias, {})[mode] = new
            moved = ", ".join(f"{c} {current[c]:.2f}->{new[c]:.2f} (IC {ics[c]:+.2f})"
                              for c in new if c in ics and abs(new[c] - current[c]) >= 0.005)
            report.append(f"weights {tag}: n={len(g)} - {moved or 'no meaningful change'}")


async def _learn_day_params(state: dict, report: list[str]) -> None:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.day_trade import DayTrade

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(DayTrade).where(DayTrade.status == "closed", DayTrade.entry_time >= cutoff)
        )).scalars().all()
    def _day(r):
        t = r.entry_time if r.entry_time.tzinfo else r.entry_time.replace(tzinfo=timezone.utc)
        return t.astimezone(ET).date().isoformat()

    trades = [{"reason": r.exit_reason, "pnl": r.pnl or 0.0, "pnl_pct": r.pnl_pct or 0.0,
               "held": r.held_minutes or 0, "day": _day(r)} for r in rows if r.pnl is not None]
    state["day"], notes = tune_day_params(state["day"], trades)
    report.extend(notes)


async def run_daily_learning(dry_run: bool = False) -> dict:
    """Entry point (scheduler + API). Returns the report; persists unless dry_run."""
    from app.config import settings
    if not settings.learning_enabled:
        return {"status": "disabled", "report": ["learning disabled (LEARNING_ENABLED=false)"]}

    state = load_state()
    report: list[str] = []
    try:
        await _learn_weights(state, report)
    except Exception as e:
        logger.exception("weight learning failed")
        report.append(f"weights: error {e!r}")
    try:
        await _learn_day_params(state, report)
    except Exception as e:
        logger.exception("day-param learning failed")
        report.append(f"day params: error {e!r}")

    state["history"].append({"date": datetime.now(ET).date().isoformat(), "report": report})
    if not dry_run:
        save_state(state)
        _cached["state"] = None
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.adaptive import AdaptiveEvent
            async with AsyncSessionLocal() as db:
                db.add(AdaptiveEvent(event_type="daily_learning",
                                     description="Daily learning: " + "; ".join(report)[:480],
                                     data={"report": report, "day": state["day"]}))
                await db.commit()
        except Exception as e:
            logger.warning(f"Could not log learning event: {e}")
    for line in report:
        logger.info(f"[LEARN] {line}")
    return {"status": "ok", "dry_run": dry_run, "report": report, "day": state["day"],
            "weights": state["weights"]}
