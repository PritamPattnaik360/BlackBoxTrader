"""
Tradable universe: the S&P 500 plus a curated list of growth stocks.

Scanning ~550 names with FinBERT + the full quant stack every few minutes is
far too slow, so the scanner works in two stages:

  1. screen() — ONE batched daily-bar download for the whole universe, ranked
     with cheap vectorised metrics, depending on the market bias:
        bull    → relative strength vs SPY, 52-week-high proximity, volume surge
        neutral → relative strength, with a bonus for pullbacks to the 50-DMA
        bear    → oversold-bounce candidates (low RSI near support) and the
                  few names holding up best vs SPY
     A separate "day" ranking picks liquid, volatile names with a volume surge.
  2. The full NLP + quant analysis then only runs on the top candidates plus
     the user's watchlist.
"""
import io
import json
import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parents[4] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
_SP500_CACHE = CACHE_DIR / "sp500_constituents.json"
SP500_TTL_DAYS = 7
SCREEN_TTL_SECONDS = 30 * 60

# Used only if Wikipedia can't be reached and there's no cached list.
_SP500_FALLBACK = (
    "AAPL MSFT NVDA AMZN GOOGL META BRK-B AVGO LLY TSLA JPM V UNH XOM WMT MA COST HD PG JNJ ORCL "
    "ABBV BAC NFLX CRM CVX KO MRK AMD WFC CSCO PEP ADBE ACN TMO LIN MCD ABT NOW DIS IBM GE CAT "
    "QCOM TXN INTU VZ AMGN ISRG PM GS BKNG SPGI RTX NEE T LOW HON UNP PFE AXP BLK AMAT ETN SYK "
    "PGR COP TJX DE MU LRCX ADI KLAC PANW BSX C VRTX FI SCHW ADP MDT BX CB GILD MMC LMT SBUX "
    "ANET INTC UBER CME ICE MO SO DUK APH CDNS SNPS CRWD MAR REGN WM PLD AMT CI ZTS ABNB"
).split()

# Growth names outside (or on the edge of) the S&P 500. Any that have been
# delisted/renamed simply drop out of the screen when yfinance returns no data.
GROWTH_STOCKS = (
    "PLTR SNOW NET DDOG SHOP XYZ ROKU COIN MELI SE ARM SMCI ZS MDB TTD DKNG HOOD APP RKLB AFRM "
    "SOFI CELH DUOL IOT TOST CAVA ONON DASH RBLX U PATH S OKTA TWLO HUBS BILL ENPH FSLR "
    "CRSP NU CPNG LULU DECK AXON VRT ALAB ASTS IONQ"
).split()

_screen_cache: dict = {"ts": 0.0, "bias": None, "data": None}


# ── Constituents ──────────────────────────────────────────────────────────────

def get_sp500() -> list[str]:
    """S&P 500 tickers (yfinance format). Cached for a week; falls back to a static top-100."""
    try:
        if _SP500_CACHE.exists():
            age_days = (time.time() - _SP500_CACHE.stat().st_mtime) / 86400
            if age_days < SP500_TTL_DAYS:
                return json.loads(_SP500_CACHE.read_text())
    except Exception:
        pass

    try:
        import requests
        r = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 BlackBoxTrader"}, timeout=15,
        )
        r.raise_for_status()
        html = r.text
        table = html[html.find('id="constituents"'):]
        table = table[: table.find("</table>")]
        syms = re.findall(r'class="external text"[^>]*>([A-Z.\-]{1,6})</a></td>', table)
        syms = [s.replace(".", "-") for s in syms]
        if len(syms) >= 400:
            _SP500_CACHE.write_text(json.dumps(syms))
            logger.info(f"Loaded {len(syms)} S&P 500 constituents")
            return syms
        logger.warning(f"S&P 500 parse returned only {len(syms)} symbols")
    except Exception as e:
        logger.warning(f"Could not fetch S&P 500 list: {e}")

    try:
        if _SP500_CACHE.exists():            # stale cache beats the static list
            return json.loads(_SP500_CACHE.read_text())
    except Exception:
        pass
    return list(_SP500_FALLBACK)


def get_universe() -> list[str]:
    seen, out = set(), []
    for t in get_sp500() + GROWTH_STOCKS:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── Screening ─────────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss = (-delta).clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    rs = gain.iloc[-1] / max(loss.iloc[-1], 1e-9)
    return float(100 - 100 / (1 + rs))


def _metrics(df: pd.DataFrame, spy_ret_63: float) -> dict | None:
    df = df.dropna(subset=["Close"])
    if len(df) < 70:
        return None
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    price = float(close.iloc[-1])
    if price < 5:
        return None
    dollar_vol = float((close.tail(20) * vol.tail(20)).mean())
    if dollar_vol < 20e6:                       # liquidity floor
        return None

    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.tail(14).mean() / price)
    ma50 = float(close.tail(50).mean())
    ret_63 = price / float(close.iloc[-64]) - 1 if len(close) > 64 else 0.0
    ret_5 = price / float(close.iloc[-6]) - 1
    hi_252 = float(high.tail(252).max())
    avg_vol_50 = float(vol.tail(50).mean())
    vol_surge = float(vol.tail(3).mean() / avg_vol_50) if avg_vol_50 > 0 else 1.0

    return {
        "price": round(price, 2),
        "rs_63d": ret_63 - spy_ret_63,
        "ret_63d": ret_63,
        "ret_5d": ret_5,
        "rsi": _rsi(close),
        "atr_pct": atr_pct,
        "pct_from_high": price / hi_252 - 1,
        "above_ma50": price > ma50,
        "dist_ma50": price / ma50 - 1,
        "vol_surge": vol_surge,
        "dollar_vol_m": round(dollar_vol / 1e6, 1),
    }


def _z(s: pd.Series) -> pd.Series:
    sd = s.std()
    # Clip at ±3σ so a single outlier (e.g. a biotech gap) can't dominate the ranking
    return ((s - s.mean()) / sd).clip(-3, 3) if sd and not np.isnan(sd) else s * 0


def _rank(m: pd.DataFrame, bias: str) -> pd.Series:
    if bias == "bear":
        # Bounce candidates: oversold but liquid, plus relative-strength survivors
        bounce = _z((40 - m["rsi"]).clip(lower=0)) + 0.5 * _z(m["vol_surge"])
        survivors = _z(m["rs_63d"]) + _z(-m["atr_pct"])
        return 0.6 * bounce + 0.4 * survivors
    if bias == "bull":
        return (_z(m["rs_63d"]) + 0.7 * _z(m["pct_from_high"])
                + 0.5 * _z(m["vol_surge"]) + 0.5 * m["above_ma50"].astype(float))
    # neutral: strength with a bonus for orderly pullbacks to the 50-DMA
    pullback = (m["dist_ma50"].abs() < 0.03).astype(float)
    return _z(m["rs_63d"]) + 0.5 * _z(m["vol_surge"]) + 0.5 * pullback * m["above_ma50"].astype(float)


def screen(bias: str, top_swing: int = 15, top_day: int = 10, force: bool = False) -> dict:
    """
    Blocking. Returns {"swing": [...], "day": [...], "universe_size": n, "bias": bias,
    "details": {ticker: metrics}}. Cached for SCREEN_TTL_SECONDS per bias.
    """
    import yfinance as yf

    c = _screen_cache
    if (not force and c["data"] is not None and c["bias"] == bias
            and time.time() - c["ts"] < SCREEN_TTL_SECONDS):
        return c["data"]

    universe = get_universe()
    logger.info(f"Screening {len(universe)} tickers (bias={bias})...")
    try:
        raw = yf.download(universe + ["SPY"], period="1y", interval="1d", group_by="ticker",
                          progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        logger.warning(f"Universe download failed: {e}")
        return c["data"] or {"swing": [], "day": [], "universe_size": len(universe),
                             "bias": bias, "details": {}}

    spy = raw["SPY"]["Close"].dropna()
    spy_ret_63 = float(spy.iloc[-1] / spy.iloc[-64] - 1) if len(spy) > 64 else 0.0

    rows = {}
    for t in universe:
        try:
            if t in raw.columns.get_level_values(0):
                mt = _metrics(raw[t], spy_ret_63)
                if mt:
                    rows[t] = mt
        except Exception:
            continue

    if not rows:
        return c["data"] or {"swing": [], "day": [], "universe_size": len(universe),
                             "bias": bias, "details": {}}

    m = pd.DataFrame(rows).T
    for col in ("rs_63d", "ret_63d", "ret_5d", "rsi", "atr_pct", "pct_from_high",
                "dist_ma50", "vol_surge", "dollar_vol_m"):
        m[col] = m[col].astype(float)
    m["above_ma50"] = m["above_ma50"].astype(bool)

    m["swing_score"] = _rank(m, bias)
    swing = m.sort_values("swing_score", ascending=False).head(top_swing).index.tolist()

    # Day-trade candidates: enough range to trade (1.5–7% ATR), very liquid, volume in play
    dt = m[(m["atr_pct"].between(0.015, 0.07)) & (m["dollar_vol_m"] > 100)].copy()
    dt["day_score"] = _z(dt["atr_pct"]) + _z(dt["vol_surge"]) + 0.3 * _z(dt["ret_5d"].abs())
    day = [t for t in dt.sort_values("day_score", ascending=False).index if t not in swing][:top_day]

    details = {
        t: {k: (round(float(m.at[t, k]), 4) if k != "above_ma50" else bool(m.at[t, k]))
            for k in ("price", "rs_63d", "rsi", "atr_pct", "vol_surge", "pct_from_high", "above_ma50")}
        for t in swing + day
    }
    data = {"swing": swing, "day": day, "universe_size": len(m), "bias": bias, "details": details}
    c.update(ts=time.time(), bias=bias, data=data)
    logger.info(f"Screen done: {len(m)} eligible → swing={swing} day={day}")
    return data


def get_cached_screen() -> dict | None:
    return _screen_cache["data"]
