import yfinance as yf
import pandas as pd
from pathlib import Path
import os

CACHE_DIR = Path(__file__).parents[4] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_snapshot(ticker: str) -> dict:
    """
    Fetch current price with multiple fallbacks.
    fast_info.last_price is unreliable in newer yfinance — falls back to
    previous_close then 1-min history then daily history so price is
    almost never None.
    """
    t = yf.Ticker(ticker)
    info = t.fast_info

    price = getattr(info, "last_price", None)

    # Fallback 1: previous close (always available, even after hours)
    if not price:
        price = getattr(info, "previous_close", None)

    # Fallback 2: last bar from 1-min intraday history
    if not price:
        try:
            hist = t.history(period="1d", interval="1m", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    # Fallback 3: last daily close
    if not price:
        try:
            hist = t.history(period="5d", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    return {
        "ticker": ticker,
        "price": float(price) if price else None,
        "open": getattr(info, "open", None),
        "high": getattr(info, "day_high", None),
        "low": getattr(info, "day_low", None),
        "volume": getattr(info, "three_month_average_volume", None),
        "market_cap": getattr(info, "market_cap", None),
    }


def get_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    cache_path = CACHE_DIR / f"{ticker}_{interval}.parquet"
    if cache_path.exists():
        age_hours = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(cache_path), unit="s")).total_seconds() / 3600
        if age_hours < 24:
            return pd.read_parquet(cache_path)

    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        return df

    # yfinance ≥0.2.x returns MultiIndex columns (field, ticker) for single tickers.
    # Flatten to single-level lowercase strings regardless of version.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    df.to_parquet(cache_path)
    return df


def get_intraday_5m(ticker: str) -> pd.DataFrame:
    """Fetch today's 5-minute bars. Never cached — always fresh."""
    df = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    return df


def get_options_chain(ticker: str, expiry: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = yf.Ticker(ticker)
    dates = t.options
    if not dates:
        return pd.DataFrame(), pd.DataFrame()
    target = expiry if expiry and expiry in dates else dates[0]
    chain = t.option_chain(target)
    return chain.calls, chain.puts
