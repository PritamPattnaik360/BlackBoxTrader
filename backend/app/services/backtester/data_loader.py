import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import os

CACHE_DIR = Path(__file__).parents[4] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# yfinance free tier: max 60 days of 5-minute bars
INTRADAY_MAX_DAYS = 59


def load_ohlcv(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    cache_path = CACHE_DIR / f"{ticker}_{interval}_bt.parquet"
    try:
        if cache_path.exists():
            age_h = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(cache_path), unit="s")).total_seconds() / 3600
            if age_h < 24:
                df = pd.read_parquet(cache_path)
                mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
                return df[mask]
    except Exception:
        pass

    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        return df
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df.to_parquet(cache_path)
    return df


def load_intraday_ohlcv(ticker: str, start: str, end: str, interval: str = "5m") -> pd.DataFrame:
    """
    Load intraday OHLCV bars. yfinance caps free 5m data at 60 days back,
    so start is silently clamped to that limit.
    Returns a DataFrame with a tz-aware DatetimeIndex (America/New_York).
    """
    earliest = datetime.utcnow().date() - timedelta(days=INTRADAY_MAX_DAYS)
    start_dt = max(pd.Timestamp(start).date(), earliest)
    end_dt   = pd.Timestamp(end).date()

    # Short cache (6 hours) — intraday data is live
    cache_path = CACHE_DIR / f"{ticker}_{interval}_intraday_bt.parquet"
    try:
        if cache_path.exists():
            age_h = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(cache_path), unit="s")).total_seconds() / 3600
            if age_h < 6:
                df = pd.read_parquet(cache_path)
                mask = (df.index.date >= start_dt) & (df.index.date <= end_dt)
                return df[mask]
    except Exception:
        pass

    import yfinance as yf
    df = yf.download(
        ticker,
        start=str(start_dt),
        end=str(end_dt + timedelta(days=1)),
        interval=interval,
        progress=False,
        auto_adjust=True,
    )
    if df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    # Normalize index to ET
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    df.to_parquet(cache_path)
    mask = (df.index.date >= start_dt) & (df.index.date <= end_dt)
    return df[mask]
