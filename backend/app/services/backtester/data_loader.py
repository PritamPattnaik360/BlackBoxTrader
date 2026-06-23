import pandas as pd
from pathlib import Path
import os

CACHE_DIR = Path(__file__).parents[5] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
