"""
Day-trade pattern analysis.

Breaks closed day trades down by hour of day, score band, market bias, side, ticker and (when the
entry snapshot recorded them) relative volume and VIX. A bucket is only reported as a pattern when
it has enough trades, and only flagged "avoid" when it lost money in BOTH the earlier 70% of trades
and the most recent 30% — so a one-off bad week can't block a time window.

Pure functions on plain dicts so they can be unit-tested; the DB loading lives in the callers.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

MIN_BUCKET   = 20      # trades needed before a bucket is reported as a pattern
MIN_TEST     = 5       # trades the bucket needs in the held-out slice to be judged
TRAIN_SHARE  = 0.70
MAX_AVOID_HOURS = 2    # never block more than this many hours of the session

SCORE_BANDS = ((0.35, "<0.35"), (0.50, "0.35-0.50"), (0.70, "0.50-0.70"), (9.0, "0.70+"))
RVOL_BANDS  = ((1.0, "<1x"), (1.5, "1-1.5x"), (2.5, "1.5-2.5x"), (999.0, "2.5x+"))
VIX_BANDS   = ((16.0, "<16"), (22.0, "16-22"), (30.0, "22-30"), (999.0, "30+"))

DIMENSIONS = ("hour", "score", "bias", "side", "ticker", "rvol", "vix")


def _band(value: float | None, bands) -> str | None:
    if value is None:
        return None
    for hi, label in bands:
        if value < hi:
            return label
    return bands[-1][1]


def trade_keys(t: dict) -> dict:
    """Bucket label for each dimension (None where the trade has no data for it)."""
    when = t["entry_time"]
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    f = t.get("features") or {}
    score = t.get("score")
    return {
        "hour":   f"{when.astimezone(ET).hour:02d}:00",
        "score":  _band(abs(score) if score is not None else None, SCORE_BANDS),
        "bias":   t.get("bias"),
        "side":   t.get("side") or "long",
        "ticker": t.get("ticker"),
        "rvol":   _band(f.get("rvol"), RVOL_BANDS),
        "vix":    _band(f.get("vix"), VIX_BANDS),
    }


def _summ(pnls: list[float]) -> dict:
    n = len(pnls)
    return {"n": n, "wins": sum(1 for p in pnls if p > 0), "net": round(sum(pnls), 2),
            "avg": round(sum(pnls) / n, 2) if n else 0.0}


def analyze(trades: list[dict], min_n: int = MIN_BUCKET) -> dict:
    """
    `trades`: dicts with entry_time, pnl, score, bias, side, ticker, features. Returns
    {"n": total, "buckets": [...], "avoid": [...]} — buckets sorted worst-first within a dimension.
    """
    trades = sorted((t for t in trades if t.get("pnl") is not None), key=lambda t: t["entry_time"])
    cut = int(len(trades) * TRAIN_SHARE)
    keyed = [(trade_keys(t), t["pnl"], i >= cut) for i, t in enumerate(trades)]

    buckets = []
    for dim in DIMENSIONS:
        groups: dict[str, dict[str, list[float]]] = {}
        for keys, pnl, is_test in keyed:
            label = keys[dim]
            if label is None:
                continue
            g = groups.setdefault(label, {"all": [], "train": [], "test": []})
            g["all"].append(pnl)
            g["test" if is_test else "train"].append(pnl)
        for label, g in groups.items():
            s = _summ(g["all"])
            if s["n"] < min_n:
                continue
            tr, te = _summ(g["train"]), _summ(g["test"])
            judged = te["n"] >= MIN_TEST and tr["n"] >= MIN_TEST
            s.update(dim=dim, bucket=label, win_rate=round(s["wins"] / s["n"], 3),
                     train_avg=tr["avg"], test_avg=te["avg"], test_n=te["n"],
                     avoid=bool(judged and s["net"] < 0 and tr["avg"] < 0 and te["avg"] < 0))
            buckets.append(s)
    buckets.sort(key=lambda b: (DIMENSIONS.index(b["dim"]), b["net"]))
    return {"n": len(trades), "min_bucket": min_n, "buckets": buckets,
            "avoid": [b for b in buckets if b["avoid"]]}


def avoid_hours(report: dict) -> list[int]:
    """Entry hours (ET) to stop trading: validated losing hours, worst first, capped."""
    hours = sorted((b for b in report["avoid"] if b["dim"] == "hour"), key=lambda b: b["net"])
    return sorted(int(b["bucket"][:2]) for b in hours[:MAX_AVOID_HOURS])


def post_mortem(losses: list[dict]) -> list[str]:
    """
    Plain-language review of one day's stop-outs: what they cost, how wide the stops were and how
    quickly they were hit. `losses`: dicts with ticker, pnl, entry_price, stop_price, held, score.
    """
    if not losses:
        return []
    lines = [f"loss review: {len(losses)} stop-out(s), ${sum(l['pnl'] for l in losses):,.0f} total"]
    for l in sorted(losses, key=lambda l: l["pnl"]):
        dist = abs(l["entry_price"] - l["stop_price"]) / l["entry_price"] if l.get("stop_price") and l["entry_price"] else None
        quick = "stopped within 5 min" if l["held"] <= 5 else f"held {l['held']}m"
        lines.append(f"  {l['ticker']} ${l['pnl']:,.0f}: score {l['score']}, "
                     f"stop {dist:.1%} away, {quick}" if dist is not None else f"  {l['ticker']} ${l['pnl']:,.0f}: {quick}")
    repeats = sorted({l["ticker"] for l in losses if sum(1 for x in losses if x["ticker"] == l["ticker"]) > 1})
    if repeats:
        lines.append(f"  re-entered after a stop and lost again: {', '.join(repeats)} (the loss guard now blocks this)")
    fast = sum(1 for l in losses if l["held"] <= 5)
    if fast >= 2:
        lines.append(f"  {fast} stops hit within 5 minutes — entries are chasing moves that are already reversing")
    return lines


def trade_dicts(rows) -> list[dict]:
    """DayTrade ORM rows -> analysis dicts."""
    return [{"entry_time": r.entry_time, "pnl": r.pnl, "score": r.quant_score, "bias": r.bias,
             "side": getattr(r, "side", None) or "long", "ticker": r.ticker,
             "features": getattr(r, "features", None)} for r in rows if r.pnl is not None]
